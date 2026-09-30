"""Pure, testable business rules; no network calls or credentials."""
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

WEBSITE = 'https://wizefftopup.com/'

def norm(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text or '').lower()).strip()


def tr(language, banglish, bangla, english):
    return {'Bangla': bangla, 'English': english}.get(language, banglish)


def sensitive(text):
    """Reject credential-bearing input before persistence or LLM transmission.

    Unlabelled secrets cannot be identified perfectly; this intentionally errs on
    the side of rejecting labelled credentials and card/token-shaped strings.
    """
    return bool(re.search(
        r'(?i)\b(?:password|passwd|otp|pin|cvv|cvc|recovery\s*code|api[ _-]?key|'
        r'access[ _-]?token|secret[ _-]?key|card\s*(?:number|no))\b'
        r'|পাসওয়ার্ড|পাসওয়ার্ড|ওটিপি|পিন|গোপন কোড'
        r'|\b(?:gsk_|sk-|sb_secret_)[\w-]{12,}'
        r'|\b\d{8,12}:[A-Za-z0-9_-]{25,}'
        r'|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
        r'|(?<!\d)(?:\d[ -]?){13,19}(?!\d)', text or ''))


def safe_text(text):
    return '[Sensitive information omitted]' if sensitive(text) else (text or '')[:4000]


def language_for(text, previous=''):
    low = norm(text)
    words = re.findall(r'[a-z]+', low)
    if not re.search(r'[a-z\u0980-\u09ff]', low):
        return previous or 'Banglish'
    if low in {'hi','hello','hey','ok','okay','yes','no','acha','accha','thanks','হাই','ওকে','আচ্ছা'}:
        return previous or ('Bangla' if re.search(r'[\u0980-\u09ff]', low) else 'Banglish')
    if re.search(r'[\u0980-\u09ff]', low):
        return 'Bangla'
    if set(words) & set('ami apni tumi tmi vai vaiya bhai ache ase nai koro korbo lagbe diben den ki koto hobe pabo hoise hoy bolo bolen bujhi kisu kichu ekhon dao daw sawwa taka hoitase hocche hoisos eta korba rakhar try ans diba'.split()):
        return 'Banglish'
    english = set(words) & set('the is are can could would please what why where when how my your this that with for from need want'.split())
    return 'English' if len(english) >= 2 else (previous or 'Banglish')


def payment_problem(text):
    t = norm(text)
    return bool(re.search(r'(?:taka|balance)\s+add\s+(?:hocche|hoitase|hoy|hoi|hoche|hoyni|hoynai)', t)) or any(x in t for x in (
        'payment pending','pending payment','money deducted','taka kete','taka katse',
        'টাকা কেটে','টাকা অ্যাড হচ্ছে না','টাকা এড হচ্ছে না','টাকা যোগ হয়নি','ব্যালেন্স যোগ',
        'payment failed','paid but','payment complete but','balance add hoy nai',
        'balance ashe nai','topup pai nai','top up pai nai','order pending','pending order',
        'পেমেন্ট পেন্ডিং','অর্ডার পেন্ডিং','টপআপ পাই নাই'))


def updates_intent(text):
    return bool(re.search(r'(?i)(?:updates?|announcements?|news)\s+(?:link|channel)|'
                         r'telegram\s+channel|website\s+update\s+channel|'
                         r'টেলিগ্রাম\s*চ্যানেল|আপডেট\s*(?:লিংক|চ্যানেল)', text or ''))


def reference_id(text, expected=False):
    t = (text or '').translate(str.maketrans('০১২৩৪৫৬৭৮৯','0123456789'))
    if sensitive(t):
        return ''
    labelled = re.findall(r'(?i)(?:order|reference|ref|transaction|trx)(?:\s*id)?\s*[:#=-]?\s*([A-Z0-9-]{5,32})\b', t)
    labelled = [x for x in labelled if re.search(r'\d', x)]
    if labelled:
        return labelled[-1]
    if expected:
        match = re.fullmatch(r'\s*([A-Za-z0-9-]{5,32})(?:\s+(?:eta|eita|this|এইটা|এটা))?[.! ]*', t, re.I)
        if match and re.search(r'\d', match[1]):
            return match[1]
    return ''


def unsafe_category(text):
    return bool(re.search(r'(?i)teen\s*patti|casino|gambl|betting|1xbet|adult|porn|'
                         r'number.?to.?(?:nid|location)|nid|কল\s*লিস্ট|call.?list|'
                         r'নাম্বার|নম্বর|follower|followers|fb.like|free.fire.like|লাইক|'
                         r'tiktok.*like|ig.*like', text or ''))


def product_url(url):
    parsed = urlsplit(urljoin(WEBSITE, url))
    if parsed.scheme != 'https' or parsed.netloc != 'wizefftopup.com' or parsed.username:
        return ''
    if not re.fullmatch(r'/product/[a-zA-Z0-9_-]+/?', parsed.path):
        return ''
    return urlunsplit(('https', 'wizefftopup.com', parsed.path.rstrip('/'), '', ''))


def aliases_for(name):
    n = norm(name)
    aliases = {n, n.replace(' ', '')}
    if 'capcut' in n: aliases |= {'capcut','cap cut','capcut pro'}
    if 'glory' in n and 'bot' in n: aliases |= {'glory','glory bot','glorybot','glori bot','guild glory bot'}
    if 'guild' in n and 'tcp' in n: aliases |= {'guild','guild bot','guildbot','gild bot','gu ild bot','tcp bot','guild tcp bot'}
    if n == 'guild bot': aliases |= {'guild','guildbot','gild bot'}
    return sorted(aliases)


class CatalogParser(HTMLParser):
    """Extract product anchors only; exclude site scripts and customer feeds."""
    def __init__(self):
        super().__init__(); self.products = {}; self.anchor = None; self.parts = []; self.alt = ''; self.skip = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script','style'}: self.skip += 1
        if tag == 'a':
            self.anchor = product_url(attrs.get('href','')); self.parts = []; self.alt = ''
        if tag == 'img' and self.anchor and attrs.get('alt'):
            self.alt = attrs['alt']
    def handle_data(self, data):
        if self.anchor and not self.skip: self.parts.append(data.strip())
    def handle_endtag(self, tag):
        if tag in {'script','style'}: self.skip = max(0, self.skip-1)
        if tag == 'a' and self.anchor:
            name = re.sub(r'\b(?:Hot Deal|Best Selling|Popular|Trending|New|1 Year Special)\b', '', ' '.join(self.parts) or self.alt, flags=re.I)
            name = re.sub(r'\s+', ' ', name).strip()[:120]
            if name and not unsafe_category(name+' '+self.anchor):
                self.products[self.anchor] = {'name':name, 'aliases':aliases_for(name), 'url':self.anchor, 'category':'website product', 'details':''}
            self.anchor = None


def matches(text, alias):
    return bool(re.search(r'(?<!\w)'+re.escape(norm(alias))+r'(?!\w)', norm(text)))


def matched_products(text, catalog):
    found = [(max([len(a) for a in p['aliases'] if matches(text,a)] or [0]), p) for p in catalog]
    found = [(n,p) for n,p in found if n]
    # Specific "guild glory bot" must not also select a generic "guild" match.
    return [p for n,p in found if not any(n < m and any(matches(a,b) for a in q['aliases'] if matches(text,a) for b in p['aliases'] if matches(text,b)) for m,q in found)]


def canonical_service(name, catalog=()):
    found = matched_products(name, catalog)
    if len(found)==1: return norm(found[0]['name'])
    n=norm(name)
    if n in {'capcut','cap cut','capcut pro'}: return 'capcut pro'
    if n in {'guild','guildbot','guild bot','gild bot','guild tcp bot'}: return 'guild tcp bot'
    if n in {'glory','glory bot','glorybot','guild glory bot'}: return 'guild glory bot'
    return n


def extract_statuses(text, catalog=()):
    """Parse explicit status statements only; instructions mentioning status are not facts."""
    result = []
    for clause in re.split(r'[\n.;।]+|\s+(?:but|kintu)\s+', text, flags=re.I):
        clause = norm(clause)
        match = re.fullmatch(r'(.+?)\s+(?:(?:is|are|ekhon|currently|এখন|বর্তমানে)\s+)?'
                            r'(unavailable|not available|available nai|available na|available nei|'
                            r'available ache|available ase|available|পাওয়া যায় না|পাওয়া যায় না|নেই|বন্ধ|চালু|আছে)', clause)
        if not match: continue
        name,status=match.groups()
        if len(name.split()) > 7 or re.search(r'\b(?:if|when|bolle|customer|say|tell|bolba|chaiba)\b',name): continue
        is_all = bool(re.fullmatch(r'(?:all|sob|shob|সব|সকল)\s*(?:services?|apps?|products?|সার্ভিস|সেবা)(?:\s*/\s*apps?)?', name))
        unavailable = status in {'unavailable','not available','available nai','available na','available nei','পাওয়া যায় না','পাওয়া যায় না','নেই','বন্ধ'}
        result.append(('__ALL__' if is_all else canonical_service(name,catalog), 'unavailable' if unavailable else 'available'))
    return result


def fake_action(text):
    return bool(re.search(r"(?i)(?:i(?:'m| am|'ll| will| have|'ve)?|we(?:'re| are|'ll| will| have)?).{0,35}\b(?:check(?:ed|ing)?|verify|verified|verifying|forward(?:ed|ing)?|notif(?:y|ied)|refund(?:ed|ing)?)\b|"
                         r'checking now|support.{0,20}(?:notified|informed)|forwarded to|'
                         r'(?:your|the)\s+(?:order|payment|topup).{0,30}(?:completed|confirmed|successful|processed|refunded)|'
                         r'(?:order|payment).{0,12}(?:complete|confirm|refund).{0,12}(?:hoise|hoyeche|হয়েছে|হয়েছে)|'
                         r'(?:check|verify|forward|notify).{0,12}(?:korchi|korbo|korechi|korsi|kore disi)|'
                         r'(?:চেক|যাচাই|পাঠিয়ে|পাঠিয়ে|জানিয়ে|জানিয়ে).{0,18}(?:করছি|করব|করেছি|দিয়েছি|দিয়েছি|দেওয়া হয়েছে|দেওয়া হয়েছে)',text))


def unsafe_request(text):
    return sensitive(text) and bool(re.search(r'(?i)send|share|provide|give|tell|din|den|dao|দেন|দিন|পাঠান|বলুন',text))


def asks_reference(text):
    return bool(re.search(r'(?i)(?:order|reference|ref|অর্ডার|রেফারেন্স)\s*(?:/\s*(?:order|reference))?\s*(?:id|number|আইডি|নম্বর)',text)) and bool(re.search(r'(?i)please|send|provide|give|what|den|din|dao|দেন|দিন|পাঠান|\?',text))
