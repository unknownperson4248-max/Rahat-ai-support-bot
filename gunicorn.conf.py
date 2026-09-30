# One Render instance; application lock serializes updates across its workers.
# Slow external APIs must not be killed by Gunicorn's default 30-second timeout.
workers = 1
threads = 4
timeout = 180
accesslog = None


def post_worker_init(worker):
    # Render supplies this trusted URL. Re-register on deployment so existing
    # webhooks start sending the derived authentication header automatically.
    import os
    from app import configure_webhook
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if base_url:
        result = configure_webhook(base_url)
        if not result.get("ok"):
            worker.log.warning("Webhook registration failed; use authenticated /setup")
