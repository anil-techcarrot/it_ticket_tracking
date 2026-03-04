from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home
import logging

_logger = logging.getLogger(__name__)


class MicrosoftSSOHome(Home):

    @http.route('/web/session/logout', type='http', auth='none', website=True)
    def logout(self, redirect='/web/login', **kwargs):

        _logger.info("=== MICROSOFT SSO LOGOUT TRIGGERED ===")

        microsoft_logout_url = None

        try:
            uid = request.session.uid
            _logger.info("=== Current session UID: %s ===", uid)

            if uid:
                user = request.env['res.users'].sudo().browse(uid)
                _logger.info("=== User: %s | oauth_uid: %s ===", user.login, user.oauth_uid)

                if user.exists() and user.oauth_uid:
                    base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')

                    provider = request.env['auth.oauth.provider'].sudo().search(
                        [('id', '=', user.oauth_provider_id.id)], limit=1
                    )

                    _logger.info("=== Provider: %s | auth_endpoint: %s ===",
                                 provider.name if provider else 'None',
                                 provider.auth_endpoint if provider else 'None')

                    tenant_id = 'common'
                    if provider and provider.auth_endpoint:
                        parts = provider.auth_endpoint.split('/')
                        for i, part in enumerate(parts):
                            if 'login.microsoftonline.com' in part and i + 1 < len(parts):
                                tenant_id = parts[i + 1]
                                break

                    _logger.info("=== Tenant ID extracted: %s ===", tenant_id)

                    microsoft_logout_url = (
                        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/logout"
                        f"?post_logout_redirect_uri={base_url}/web/login"
                    )
                    _logger.info("=== Microsoft logout URL: %s ===", microsoft_logout_url)

                else:
                    _logger.warning("=== User has no oauth_uid — skipping Microsoft logout ===")

        except Exception as e:
            _logger.error("=== Azure SSO Logout ERROR: %s ===", e)

        # Destroy Odoo session first
        request.session.logout(keep_db=True)

        # Redirect to Microsoft logout
        if microsoft_logout_url:
            _logger.info("=== Redirecting to Microsoft logout ===")
            return request.redirect(microsoft_logout_url)

        _logger.warning("=== No Microsoft logout URL — redirecting to Odoo login ===")
        return request.redirect(redirect)