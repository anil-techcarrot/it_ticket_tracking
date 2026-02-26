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

        # Check if user already exists
        user = self.sudo().search([('login', '=', email)], limit=1)

        if user:
            # User exists — just link oauth_uid if not linked yet
            if oauth_uid and not user.oauth_uid:
                user.sudo().write({
                    'oauth_uid': oauth_uid,
                    'oauth_provider_id': provider,
                })
            _logger.info("Azure SSO: Existing user login: %s", email)

        else:
            # User does NOT exist — check if email is internal domain
            internal_domains = ['techcarrot.ae']  # ← Add your company domains here
            email_domain = email.split('@')[-1].lower()

            if email_domain in internal_domains:
                # Create INTERNAL USER for company employees
                _logger.info("Azure SSO: Creating internal user for %s", email)
                env = self.env(user=SUPERUSER_ID)
                internal_group = self.env.ref('base.group_user')
                user = env['res.users'].with_context(
                    no_reset_password=True,
                ).create({
                    'name': validation.get('name', email),
                    'login': email,
                    'email': email,
                    'active': True,
                    'group_ids': [(6, 0, [internal_group.id])],
                })
            else:
                # Create PORTAL USER for external users
                _logger.info("Azure SSO: Creating portal user for %s", email)
                env = self.env(user=SUPERUSER_ID)
                portal_group = self.env.ref('base.group_portal')
                user = env['res.users'].with_context(
                    no_reset_password=True,
                ).create({
                    'name': validation.get('name', email),
                    'login': email,
                    'email': email,
                    'active': True,
                    'group_ids': [(6, 0, [portal_group.id])],
                })

            # Link oauth_uid
            if oauth_uid:
                user.sudo().write({
                    'oauth_uid': oauth_uid,
                    'oauth_provider_id': provider,
                })

            _logger.info("Azure SSO: User created successfully: %s", email)

        return super()._auth_oauth_signin(provider, validation, params)