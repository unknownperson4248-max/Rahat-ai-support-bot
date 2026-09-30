import copy
import importlib
import json
import os
from pathlib import Path
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

os.environ.pop('SUPABASE_URL',None)
os.environ.pop('SUPABASE_SECRET_KEY',None)
import app
from assistant_rules import *


class MemoryDB:
    def __init__(self): self.rows=[]; self.next_id=1
    def request(self,method,params=None,payload=None,representation=False):
        params=params or {}
        def included(row):
            for key,query in params.items():
                if key in {'select','order','limit','offset'}: continue
                value=str(row.get(key,''))
                if query.startswith('eq.') and value!=query[3:]: return False
                if query.startswith('in.(') and value not in query[4:-1].split(','): return False
                if query.startswith('gte.') and value<query[4:]: return False
                if query.startswith('lt.') and value>=query[3:]: return False
            return True
        selected=[r for r in self.rows if included(r)]
        if method=='GET':
            selected.sort(key=lambda r:r['id'],reverse=params.get('order')=='id.desc')
            start=int(params.get('offset',0)); end=start+int(params.get('limit',100000))
            return copy.deepcopy(selected[start:end])
        if method=='POST':
            self.rows.append({**payload,'id':self.next_id,'created_at':app.now_iso()}); self.next_id+=1
        if method=='PATCH':
            for row in selected: row.update(payload)
            return copy.deepcopy(selected)
        if method=='DELETE': self.rows=[r for r in self.rows if not included(r)]
        return None


class AppTests(unittest.TestCase):
    def setUp(self):
        self.db=MemoryDB(); self.sent=[]; self.calls=[]
        self.patches=[patch.object(app,'db_request',self.db.request),
                      patch.object(app,'OWNER_TELEGRAM_ID',99),
                      patch.object(app,'TELEGRAM_TOKEN','test-token'),
                      patch.object(app,'catalog_products',lambda:app.validate_catalog(json.loads(Path('catalog_seed.json').read_text())['products'])),
                      patch.object(app,'send_message',self.send),
                      patch.object(app,'get_business_info',return_value={'owner_id':99,'user_chat_id':99,'can_reply':True}),
                      patch.object(app,'ask_groq',self.groq),
                      patch.dict(os.environ,{'TELEGRAM_WEBHOOK_SECRET':''})]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
        self.client=app.app.test_client(); self.update_id=0
        self.client.environ_base['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN']=app.webhook_secret()
    def send(self,chat_id,text,*args,**kwargs):
        self.sent.append((chat_id,text,kwargs)); return {'ok':True}
    def groq(self,*args,**kwargs):
        self.calls.append((args,kwargs)); return {'reply':'Thik ache, bolen.','needs_human':False}
    def msg(self,text,sender=7,connection='business-one',reply=None):
        m={'message_id':self.update_id+100,'chat':{'id':7,'type':'private'},'from':{'id':sender,'first_name':'Riazur Rahman','username':'Topupuowo'},'text':text}
        if connection: m['business_connection_id']=connection
        else:m['chat']['id']=sender
        if reply:m['reply_to_message']=reply
        return m
    def dispatch(self,text,sender=7,connection='business-one',reply=None,edited=False):
        self.update_id+=1; m=self.msg(text,sender,connection,reply)
        kind='edited_business_message' if edited else ('business_message' if connection else 'message')
        return self.client.post('/webhook',json={'update_id':self.update_id,kind:m})
    def key(self,connection='business-one'):return app.scope_key(7,7,connection)
    def test_reference_followup_and_cooldown(self):
        self.assertEqual(self.dispatch('Taka add hoitase na').status_code,200)
        self.assertIn('ID-ta den',self.sent[-1][1]); self.assertFalse(self.calls)
        self.dispatch('829292828 eta')
        self.assertIn('829292828 peyechi',self.sent[-1][1])
        alerts=[m for m in self.sent if m[0]==99]; self.assertEqual(len(alerts),1)
        self.assertIn('829292828',alerts[0][1]); self.assertNotIn('assistant:',alerts[0][1])
        before=app.get_json('support_case',self.key())['alerted_at']
        app.save_support_case(self.key(),'same issue','more context')
        app.notify_owner(99,{'id':7},'followup',key=self.key(),ref_id='829292829')
        self.assertEqual(app.get_json('support_case',self.key())['alerted_at'],before)
        self.assertEqual(len([m for m in self.sent if m[0]==99]),1)
    def test_failed_notification_does_not_mark_alert(self):
        with patch.object(app,'send_message',return_value={'ok':False}):
            self.assertFalse(app.notify_owner(99,{'id':7},'issue',key=self.key(),ref_id='123456789'))
        self.assertNotIn('alerted_at',app.get_json('support_case',self.key()))
    def test_owner_manual_silent(self):
        self.dispatch('ami dekhtasi',sender=99)
        self.assertFalse(self.sent); self.assertFalse(self.calls)
        self.assertEqual(app.load_recent_messages(self.key())[-1]['text'],'ami dekhtasi')
    def test_off_and_explicit_customer_ai(self):
        self.dispatch('/off',sender=99,connection=None); self.sent.clear()
        self.dispatch('hello'); self.assertFalse(self.sent)
        self.dispatch('/ai hello'); self.assertEqual(len(self.sent),1)
        app.save_state_key('auto_reply',True)
        self.dispatch('hello'); self.assertEqual(len(self.sent),2)
    def test_help_role_and_no_command_memory(self):
        self.dispatch('/help'); self.assertNotIn('/gk',self.sent[-1][1])
        self.assertEqual(app.load_recent_messages(self.key()),[])
        self.dispatch('/help',sender=99,connection=None); self.assertIn('/gk',self.sent[-1][1])
        self.dispatch('/help',sender=99); self.assertEqual(self.sent[-1][0],99)
    def test_owner_reply_ai_targets_customer_and_works_off(self):
        app.save_state_key('auto_reply',False)
        self.dispatch('/ai ans',sender=99,reply=self.msg('Taka add hoitase na'))
        self.assertIn('ID-ta den',self.sent[-1][1]); self.assertNotIn('Hi',self.sent[-1][1])
    def test_owner_standalone_ai_not_knowledge(self):
        self.dispatch('/ai short ans korar try koro',sender=99)
        self.assertTrue(self.calls[-1][1]['owner']); self.assertEqual(app.load_knowledge(),[])
    def test_owner_private_normal_uses_groq_no_permanent_memory(self):
        self.dispatch('CapCut unavailable',sender=99,connection=None)
        self.assertTrue(self.calls); self.assertFalse(app.load_knowledge())
        self.assertEqual(app.load_state()['service_status'],{})
    def test_gk_refresh_deterministic_service_status(self):
        for text in ['All services available','CapCut Pro available nai']:
            self.dispatch('/gk '+text,sender=99,connection=None)
        self.calls.clear(); self.dispatch('Capcut need')
        self.assertIn('available nei',self.sent[-1][1]); self.assertFalse(self.calls)
        self.dispatch('/gk CapCut Pro available ache',sender=99,connection=None)
        self.dispatch('Capcut need'); self.assertTrue(self.calls)
        self.assertEqual(self.calls[-1][0][5]['service_status']['capcut pro'],'available')
    def test_old_gk_without_status_row_enforced(self):
        app.db_insert('knowledge',None,'All services available. CapCut not available.')
        self.dispatch('capcut need'); self.assertFalse(self.calls)
        self.assertIn('available nei',self.sent[-1][1])
    def test_generic_service_status(self):
        app.add_owner_knowledge('Test Product unavailable')
        self.dispatch('test product lagbe'); self.assertFalse(self.calls)
        self.assertIn('available nei',self.sent[-1][1])
    def test_language_lock_numeric_greetings(self):
        key=self.key(); app.detect_language('amar taka add hocche na',key)
        for text in ['829292828','hi','ok','yes','acha','sawwa hi']:
            self.assertEqual(app.detect_language(text,key),'Banglish')
        self.assertEqual(app.detect_language('Where can I find my order?',key),'English')
    def test_context_survives_restart_and_isolation(self):
        app.save_temp_message(self.key(),'assistant','Order/Reference ID-ta den.')
        self.dispatch('sawwa hi')
        self.assertEqual(self.calls[-1][0][3][0]['text'],'Order/Reference ID-ta den.')
        self.dispatch('hi',connection='other-business')
        self.assertEqual(self.calls[-1][0][3],[])
    def test_edits_and_duplicate_update_ignored(self):
        self.dispatch('hi',edited=True); self.assertFalse(self.sent)
        payload={'update_id':123,'business_message':self.msg('hello')}
        self.client.post('/webhook',json=payload); self.client.post('/webhook',json=payload)
        self.assertEqual(len(self.sent),1)
    def test_registry_unique_and_name_update(self):
        app.save_customer({'id':7,'first_name':'Old','username':'old'})
        app.save_customer({'id':7,'first_name':'New'})
        self.assertEqual(len(app.list_customers()),1)
        self.assertEqual(app.list_customers()[0]['first_name'],'New')
        self.assertEqual(app.list_customers()[0]['username'],'')
    def test_cleanup_keeps_registry_support_language(self):
        for kind in ['customer','support_case','customer_language','conversation','conversation_summary','update_receipt']:
            app.db_insert(kind,'7','{}')
        for r in self.db.rows:r['created_at']='2020-01-01T00:00:00+00:00'
        app._last_cleanup_at=0; app.cleanup_old_conversations()
        self.assertEqual({r['memory_type'] for r in self.db.rows},{'customer','support_case','customer_language'})
    def test_secret_not_persisted_or_sent_to_groq(self):
        self.dispatch('my password is supersecret123')
        self.assertFalse(self.calls)
        self.assertNotIn('supersecret123',json.dumps(self.db.rows))
        self.assertNotIn('supersecret123',str(self.sent))
    def test_fake_action_guard(self):
        with patch.object(app,'ask_groq',return_value={'reply':"I'll check your order now."}):
            self.dispatch('order details')
        self.assertNotIn("I'll check",self.sent[-1][1]); self.assertIn('manual verification',self.sent[-1][1])
    def test_group_only_exact_mention(self):
        for text in ['hello','@rahatwizefake','@rahatwize']:
            m=self.msg(text); m['chat']['type']='group'; self.update_id+=1
            self.client.post('/webhook',json={'update_id':self.update_id,'message':m})
        self.assertEqual(len(self.sent),1); self.assertIn('বর্তমানে Offline',self.sent[0][1])
    def test_untrusted_business_owner_ignored(self):
        with patch.object(app,'get_business_info',return_value={'owner_id':100,'can_reply':True}):
            self.dispatch('/gk All services available',sender=100)
        self.assertEqual(app.load_knowledge(),[]); self.assertFalse(self.sent)
    def test_webhook_secret_and_setup_auth(self):
        with patch.dict(os.environ,{'TELEGRAM_WEBHOOK_SECRET':'test-secret'}):
            self.assertEqual(self.client.post('/webhook',json={}).status_code,403)
            self.assertEqual(self.client.post('/webhook',json={},headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'}).status_code,200)
        self.assertEqual(self.client.get('/setup').status_code,403)


class RulesTests(unittest.TestCase):
    def test_payment_variants(self):
        for t in ['taka add hocche na','taka add hoitase na','taka add hoy nai','balance add hoy nai','payment pending','paid but balance nai','order pending','topup pai nai']:
            self.assertTrue(payment_problem(t),t)
    def test_update_intent(self):
        self.assertFalse(updates_intent('Update hoisos'))
        for t in ['update link','telegram channel','website update channel','latest announcement link']:self.assertTrue(updates_intent(t),t)
    def test_status_chronology_parser(self):
        self.assertEqual(extract_statuses('All services available. CapCut not available.'),[('__ALL__','available'),('capcut pro','unavailable')])
        self.assertEqual(extract_statuses('Customer payment complete bolle age order ID chaiba'),[])
        self.assertEqual(extract_statuses('answer besi long korba na short rakhar try korba'),[])
    def test_catalog_excludes_unsafe_and_external_urls(self):
        parser=CatalogParser(); parser.feed('<a href="/product/guild-tcp-bot"><img alt="">GUILD TCP BOT <b>New</b></a><a href="https://evil.com/product/test">Guild</a><a href="/product/teen-patti">TEEN PATTI GOLD</a><a href="/product/number-to-nid">NUMBER TO NID/LOCATION</a>')
        products=list(parser.products.values()); self.assertEqual(len(products),1)
        self.assertEqual(products[0]['name'],'GUILD TCP BOT')
        self.assertTrue(matched_products('guildbot lagbe',products))
        self.assertEqual(product_url('https://wizefftopup.com.evil.com/product/test'),'')
    def test_verified_links_only(self):
        url='https://wizefftopup.com/product/guild-tcp-bot'
        result=app.enforce_links(f'{url} https://evil.com/fake https://wizefftopup.com/product/fake www.evil.com',[url])
        self.assertEqual(result,url)
    def test_payment_emojis_one_line_exact(self):
        self.assertNotIn('\n',app.payment_row())
        self.assertEqual(app.payment_row().count('<tg-emoji'),7)
        for value in app.PAYMENT_EMOJIS:self.assertIn(value,app.payment_row())
    def test_credentials_and_reference(self):
        self.assertEqual(reference_id('829292828 eta',True),'829292828')
        self.assertEqual(reference_id('৮২৯২৯২৮২৮ এটা',True),'829292828')
        self.assertEqual(reference_id('OTP: 123456',True),'')
        self.assertEqual(reference_id('4111111111111111',True),'')
        self.assertEqual(reference_id('ABC12345 eta',True),'ABC12345')


class AdditionalTests(AppTests):
    # Reuse setup/helpers without rerunning inherited tests in this class.
    def test_reference_asked_without_model_flag(self):
        app.save_temp_message(self.key(),'assistant','Please send your reference ID.')
        self.dispatch('829292828 eta')
        self.assertFalse(self.calls)
        self.assertIn('829292828',self.sent[-1][1])
    def test_latest_reference_during_cooldown(self):
        self.dispatch('taka add hoy nai'); self.dispatch('829292828 eta')
        before=app.get_json('support_case',self.key())['alerted_at']
        self.dispatch('829292829 eta')
        case=app.get_json('support_case',self.key())
        self.assertEqual(case['reference_id'],'829292829')
        self.assertEqual(case['alerted_at'],before)
        self.assertEqual(len([x for x in self.sent if x[0]==99]),1)
    def test_old_language_preference_migration(self):
        app.db_upsert('customer_language','7','Banglish')
        self.dispatch('hi')
        self.assertEqual(app.get_value('customer_language',self.key()),'Banglish')
    def test_non_status_gk_applied_every_turn(self):
        self.dispatch('/gk answer besi long korba na short rakhar try korba',sender=99,connection=None)
        self.dispatch('hello')
        self.assertIn('short rakhar',self.calls[-1][0][4][0]['text'])
        app.db_insert('knowledge',None,'Use one sentence when possible')
        self.dispatch('thanks')
        self.assertEqual(len(self.calls[-1][0][4]),2)
    def test_forgetlast_restores_previous_status(self):
        app.add_owner_knowledge('CapCut available')
        app.add_owner_knowledge('CapCut unavailable')
        self.dispatch('/forgetlast',sender=99,connection=None)
        self.assertEqual(app.load_state()['service_status']['capcut pro'],'available')
    def test_storage_outage_fails_closed(self):
        with patch.object(app,'db_request',side_effect=app.StorageError('test')):
            self.assertEqual(self.dispatch('hello').status_code,503)
        self.assertFalse(self.sent)
    def test_catalog_cache_and_fallback(self):
        self.patches[3].stop()  # catalog mock after db, owner ID, token
        with patch.object(app.requests,'get',return_value=Mock(status_code=200,text='<a href="/product/guild-tcp-bot">GUILD TCP BOT</a>')) as get:
            one=app.catalog_products(); two=app.catalog_products()
        self.assertEqual(one,two); self.assertEqual(get.call_count,1)
    def test_unsafe_catalog_request_not_sent_to_llm(self):
        self.dispatch('teen patti gold lagbe')
        self.assertFalse(self.calls)
    def test_stale_pending_reference_does_not_swallow_new_number(self):
        app.put_json('conversation_summary',self.key(),{'awaiting_reference':True,'updated_at':'2020-01-01T00:00:00+00:00'})
        self.dispatch('123456789')
        self.assertTrue(self.calls)
    def test_product_followup_honors_override(self):
        app.add_owner_knowledge('Guild Bot unavailable')
        app.save_temp_message(self.key(),'user','guildbot lagbe')
        self.dispatch('link dao')
        self.assertFalse(self.calls); self.assertNotIn('https://',self.sent[-1][1])
    def test_auto_setup_uses_secret_and_required_updates(self):
        with patch.object(app,'telegram_post',return_value={'ok':True}) as post:
            self.assertTrue(app.configure_webhook('https://example.onrender.com')['ok'])
        args=post.call_args.args
        self.assertEqual(args[0],'setWebhook')
        self.assertEqual(args[1]['secret_token'],app.webhook_secret())
        self.assertEqual(args[1]['allowed_updates'],['message','business_connection','business_message'])
    def test_groq_wire_format_and_history(self):
        # Stop only the Groq stub, then intercept the HTTP transport.
        self.patches[-2].stop()
        with patch.object(app,'GROQ_API_KEY','test-key'), patch.object(app.requests,'post',return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'content':'{"reply":"Hi","needs_human":false}'}}]})) as post:
            self.dispatch('hello')
        self.assertEqual(post.call_args.args[0],'https://api.groq.com/openai/v1/chat/completions')
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['messages'][0]['role'],'system')
        self.assertEqual(payload['messages'][-1]['content'],'hello')
        self.assertEqual(payload['response_format'],{'type':'json_object'})

# Unittest normally includes inherited methods. Keep each scenario once.
for _name in list(AppTests.__dict__):
    if _name.startswith('test_'):
        setattr(AdditionalTests, _name, None)

if __name__ == "__main__":
    unittest.main()
