from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        email = validation.get('email')
        if not email:
            raise Exception("Email not provided by Azure AD")

        user = self.sudo().search([('login', '=', email)], limit=1)
        if not user:
            _logger.info("Azure SSO: Creating portal user for %s", email)
            portal_group = self.env.ref('base.group_portal')
            self.sudo().create({
                'name': validation.get('name', email),
                'login': email,
                'email': email,
                'groups_id': [(6, 0, [portal_group.id])],
            })
        return super()._auth_oauth_signin(provider, validation, params)