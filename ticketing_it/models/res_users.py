from odoo import models, api, SUPERUSER_ID
import requests
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _auth_oauth_validate(self, provider, access_token):
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers=headers
        )
        if response.status_code != 200:
            raise Exception(f"Microsoft Graph error: {response.text}")
        data = response.json()

        user_id = data.get('id')
        email = data.get('mail') or data.get('userPrincipalName')

        return {
            'sub': user_id,
            'user_id': user_id,
            'id': user_id,
            'email': email,
            'name': data.get('displayName'),
            'login': email,
        }

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        email = validation.get('email')
        oauth_uid = validation.get('user_id')

        if not email:
            raise Exception("Email not provided by Azure AD")

        # Check if user exists in Odoo
        user = self.sudo().search([('login', '=', email)], limit=1)

        if not user:
            # User does NOT exist in Odoo — BLOCK LOGIN
            _logger.warning("Azure SSO: Login blocked for %s — user not found in Odoo", email)
            raise Exception("Access denied. Your account does not exist in the system. Please contact your administrator.")

        # User exists — link oauth_uid if not linked yet
        if oauth_uid and not user.oauth_uid:
            user.sudo().write({
                'oauth_uid': oauth_uid,
                'oauth_provider_id': provider,
            })

        _logger.info("Azure SSO: Existing user login success: %s", email)
        return super()._auth_oauth_signin(provider, validation, params)