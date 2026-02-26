from odoo import models, api, SUPERUSER_ID
import requests
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _auth_oauth_validate(self, provider, access_token):
        """Override to use Microsoft Graph API directly"""
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers=headers
        )
        if response.status_code != 200:
            raise Exception(f"Microsoft Graph error: {response.text}")

        data = response.json()
        return {
            'sub': data.get('id'),
            'email': data.get('mail') or data.get('userPrincipalName'),
            'name': data.get('displayName'),
        }

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        email = validation.get('email')
        if not email:
            raise Exception("Email not provided by Azure AD")

        # Check if user already exists
        user = self.sudo().search([('login', '=', email)], limit=1)

        if not user:
            _logger.info("Azure SSO: Creating portal user for %s", email)
            try:
                portal_group = self.env.ref('base.group_portal')

                # Use env with SUPERUSER_ID directly
                env = self.env(user=SUPERUSER_ID)

                new_user = env['res.users'].with_context(
                    no_reset_password=True,
                    create_user=True
                ).create({
                    'name': validation.get('name', email),
                    'login': email,
                    'email': email,
                    'active': True,
                    'groups_id': [(6, 0, [portal_group.id])],
                })

                _logger.info("Azure SSO: Portal user created: %s (id=%s)", email, new_user.id)

            except Exception as e:
                _logger.error("Azure SSO: Failed to create user %s: %s", email, str(e))
                raise

        return super()._auth_oauth_signin(provider, validation, params)