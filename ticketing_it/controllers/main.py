from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home
from werkzeug.utils import redirect as werkzeug_redirect
import logging

_logger = logging.getLogger(__name__)


class MicrosoftSSOHome(Home):

    @http.route('/web/session/logout', type='http', auth='none', website=True)
    def logout(self, redirect='/web/login', **kwargs):

        microsoft_logout_url = None

        try:
            uid = request.session.uid

            if uid:
                user = request.env['res.users'].sudo().browse(uid)

                if user.exists() and user.oauth_uid:
                    base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')

                    provider = request.env['auth.oauth.provider'].sudo().search(
                        [('id', '=', user.oauth_provider_id.id)], limit=1
                    )

                    tenant_id = 'common'
                    if provider and provider.auth_endpoint:
                        parts = provider.auth_endpoint.split('/')
                        for i, part in enumerate(parts):
                            if 'login.microsoftonline.com' in part and i + 1 < len(parts):
                                tenant_id = parts[i + 1]
                                break

                    microsoft_logout_url = (
                        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/logout"
                        f"?post_logout_redirect_uri={base_url}/web/login"
                    )
                    _logger.info("Azure SSO: Logging out user %s and redirecting to Microsoft logout", user.login)

        except Exception as e:
            _logger.error("Azure SSO: Logout hook error: %s", e)

        # Step 1: Always destroy Odoo session first
        request.session.logout(keep_db=True)

        # Step 2: Redirect to Microsoft logout using absolute URL
        if microsoft_logout_url:
            return werkzeug_redirect(microsoft_logout_url, code=302)

        # Fallback for non-SSO users
        return werkzeug_redirect(f"{request.httprequest.host_url.rstrip('/')}{redirect}", code=302)