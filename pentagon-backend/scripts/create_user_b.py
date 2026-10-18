import os
from supabase import create_client

url = os.environ["SUPABASE_URL"]
service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

admin = create_client(url, service_key)

resp = admin.auth.admin.create_user({
    "email": os.environ["SUPABASE_TEST_EMAIL_B"],
    "password": os.environ["SUPABASE_TEST_PASSWORD_B"],
    "email_confirm": True,
})
print("created:", resp.user.id, resp.user.email, resp.user.email_confirmed_at)
