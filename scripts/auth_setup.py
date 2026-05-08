"""
One-time OAuth2 authentication setup for the Graph API client.

Run this script once to authenticate via Microsoft and persist the token cache.
The GraphClient (and consumer service) will then use the cached tokens
and refresh them automatically without any user interaction.

Usage:
    python auth_setup.py

Then open http://localhost:5000/login in your browser and sign in with the
account whose Outlook calendar the service should manage.
"""

import os

import msal
from dotenv import load_dotenv
from flask import Flask, redirect, request, url_for

load_dotenv()

CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
AUTHORITY = "https://login.microsoftonline.com/common"
REDIRECT_URI = "http://localhost:5001/getAToken"
SCOPES = ["User.Read", "Calendars.ReadWrite"]
TOKEN_CACHE_FILE = os.getenv("TOKEN_CACHE_FILE", "token_cache.json")

app = Flask(__name__)
app.secret_key = os.urandom(24)

_cache = msal.SerializableTokenCache()
_msal_app = msal.ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET,
    token_cache=_cache,
)


def _save_cache() -> None:
    if _cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(_cache.serialize())


@app.route("/login")
def login():
    auth_url = _msal_app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return redirect(auth_url)


@app.route("/getAToken")
def get_token():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"Authentication error: {error} — {request.args.get('error_description')}", 400

    if not code:
        return "Missing authorization code.", 400

    result = _msal_app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    if "access_token" not in result:
        return (
            f"Token acquisition failed: {result.get('error')} — "
            f"{result.get('error_description')}",
            400,
        )

    _save_cache()
    account = result.get("id_token_claims", {}).get("preferred_username", "unknown")
    return (
        f"<h2>Authentication successful!</h2>"
        f"<p>Signed in as: <strong>{account}</strong></p>"
        f"<p>Token cache saved to <code>{TOKEN_CACHE_FILE}</code>.</p>"
        f"<p>You can close this window. The service will now use cached tokens.</p>"
    )


if __name__ == "__main__":
    print("Open http://localhost:5001/login in your browser to authenticate.")
    app.run(port=5001)
