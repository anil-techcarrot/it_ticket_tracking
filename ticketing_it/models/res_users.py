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

        user = self.sudo().search([('login', '=', email)], limit=1)

        if not user:
            _logger.info("Azure SSO: Creating portal user for %s", email)

            portal_group = self.env.ref('base.group_portal')
            env = self.env(user=SUPERUSER_ID)

            # Step 1 — Create user using _signup_create_user
            # which is the safe Odoo 19 way
            user = env['res.users'].with_context(
                no_reset_password=True,
            )._signup_create_user({
                'name': validation.get('name', email),
                'login': email,
                'email': email,
            })

            # Step 2 — Assign portal group via SQL directly
            # This bypasses the ORM field name issue entirely
            env.cr.execute("""
                DELETE FROM res_groups_users_rel 
                WHERE uid = %s
            """, (user.id,))

            env.cr.execute("""
                INSERT INTO res_groups_users_rel (uid, gid)
                VALUES (%s, %s)
            """, (user.id, portal_group.id))

            _logger.info("Azure SSO: Portal user created: %s", email)

        return super()._auth_oauth_signin(provider, validation, params)