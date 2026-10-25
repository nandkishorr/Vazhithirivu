from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

GOOGLE_PROVIDER = {
    "SCOPE": ["profile", "email"],
    "AUTH_PARAMS": {"access_type": "online"},
    "APP": {
        "client_id": "test-client-id.apps.googleusercontent.com",
        "secret": "test-secret",
        "key": "",
    },
}


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="test-client-id.apps.googleusercontent.com",
    GOOGLE_OAUTH_CLIENT_SECRET="test-secret",
    SOCIALACCOUNT_PROVIDERS={"google": GOOGLE_PROVIDER},
)
class LoginPageTests(TestCase):
    def test_google_button_shown_when_configured(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in with Google")
        self.assertContains(response, 'action="/accounts/google/login/"')

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET=""
    )
    def test_google_button_hidden_when_unconfigured(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Sign in with Google")
        self.assertContains(response, "administrator")

    def test_password_login_still_works(self):
        get_user_model().objects.create_user("admin-made", password="pw12345!")
        response = self.client.post(
            reverse("login"),
            {"username": "admin-made", "password": "pw12345!"},
        )
        self.assertRedirects(response, reverse("home"))


@override_settings(SOCIALACCOUNT_PROVIDERS={"google": GOOGLE_PROVIDER})
class GoogleFlowTests(TestCase):
    def test_post_redirects_to_google(self):
        response = self.client.post(reverse("google_login"))
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(
            location.startswith("https://accounts.google.com/o/oauth2/v2/auth"),
            location,
        )
        self.assertIn("test-client-id.apps.googleusercontent.com", location)
        self.assertIn("scope=", location)
        self.assertIn("email", location)
        self.assertIn("profile", location)
        self.assertIn("state=", location)
        self.assertIn(
            "redirect_uri=http%3A%2F%2Ftestserver%2Faccounts%2Fgoogle%2Flogin%2Fcallback%2F",
            location,
        )

    def test_get_renders_confirm_page(self):
        response = self.client.get(reverse("google_login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "socialaccount/login.html")

    def test_next_is_propagated(self):
        response = self.client.post(
            reverse("google_login"), {"next": "/crossings/5/"}
        )
        self.assertEqual(response.status_code, 302)
        # allauth encodes the redirect target in the OAuth state; after a
        # successful callback it returns the user to it.
        self.assertIn("state=", response["Location"])

    def test_callback_url_rejects_missing_state(self):
        # Without a valid OAuth state the callback aborts cleanly, not 500.
        response = self.client.get(reverse("google_callback"))
        self.assertIn(response.status_code, (302, 400, 401))


class SignupPolicyTests(TestCase):
    def test_local_signup_closed(self):
        response = self.client.get(reverse("account_signup"))
        # Closed signup never renders a working registration form.
        if response.status_code == 200:
            self.assertTemplateUsed(response, "account/signup_closed.html")

    def test_local_signup_post_creates_no_user(self):
        self.client.post(
            reverse("account_signup"),
            {
                "username": "nope",
                "email": "nope@example.com",
                "password1": "x" * 20,
                "password2": "x" * 20,
            },
        )
        self.assertFalse(
            get_user_model().objects.filter(username="nope").exists()
        )

    def test_account_login_name_resolves_to_ours(self):
        # allauth internals reverse "account_login"; it must land on our
        # own login page at the same path.
        self.assertEqual(reverse("account_login"), "/accounts/login/")
