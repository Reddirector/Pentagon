import os
from supabase import create_client

url = os.environ["SUPABASE_URL"]
service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

admin = create_client(url, service_key)

for email in [os.environ["SUPABASE_TEST_EMAIL_A"], os.environ["SUPABASE_TEST_EMAIL_B"]]:
    resp = admin.auth.admin.list_users()
    match = next((u for u in resp if u.email == email), None)
    if match is None:
        print(f"{email}: NOT FOUND in auth.users")
    else:
        print(f"{email}: found, id={match.id}, confirmed_at={match.email_confirmed_at}, created_at={match.created_at}")
