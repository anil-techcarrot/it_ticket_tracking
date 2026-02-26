from odoo import models, api
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
            # Create user without group first
            new_user = self.sudo().create({
                'name': validation.get('name', email),
                'login': email,
                'email': email,
            })
            # Then assign portal group separately
            portal_group = self.env.ref('base.group_portal')
            internal_group = self.env.ref('base.group_user')
            # Remove internal group and add portal group
            new_user.sudo().write({
                'groups_id': [
                    (3, internal_group.id),
                    (4, portal_group.id),
                ]
            })
            _logger.info("Azure SSO: Portal user created successfully for %s", email)

        return super()._auth_oauth_signin(provider, validation, params)