from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    """Local username/password accounts are provisioned by an
    administrator; public signup stays closed. Google sign-in
    self-registers through the social-account adapter (ADR-019)."""

    def is_open_for_signup(self, request):
        return False
