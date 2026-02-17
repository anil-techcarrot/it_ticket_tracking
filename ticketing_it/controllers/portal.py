# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError
import logging

_logger = logging.getLogger(__name__)


class PortalITTicket(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        """Add ticket count to portal homepage"""
        values = super()._prepare_home_portal_values(counters)

        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if employee:
            ticket_count = request.env['it.ticket'].search_count([
                ('employee_id', '=', employee.id)
            ])
            values['ticket_count'] = ticket_count
        else:
            values['ticket_count'] = 0

        return values

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_tickets(self, page=1, sortby=None, **kw):
        """List all tickets for current portal user"""
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if not employee:
            return request.render("ticketing_it.portal_no_employee")

        domain = [('employee_id', '=', employee.id)]
        ticket_count = request.env['it.ticket'].search_count(domain)

        pager = portal_pager(
            url="/my/tickets",
            total=ticket_count,
            page=page,
            step=10
        )

        tickets = request.env['it.ticket'].search(
            domain,
            limit=10,
            offset=pager['offset'],
            order='create_date desc'
        )

        values = {
            'tickets': tickets,
            'page_name': 'ticket',
            'pager': pager,
            'default_url': '/my/tickets',
        }

        return request.render("ticketing_it.portal_my_tickets", values)

    @http.route(['/my/tickets/<int:ticket_id>'], type='http', auth="user", website=True)
    def portal_ticket_detail(self, ticket_id, **kw):
        """View ticket details"""
        try:
            ticket = request.env['it.ticket'].browse(ticket_id)

            employee = request.env['hr.employee'].sudo().search([
                ('user_id', '=', request.env.user.id)
            ], limit=1)

            if not employee or ticket.employee_id != employee:
                return request.render("website.403")

            values = {
                'ticket': ticket,
                'page_name': 'ticket',
            }

            return request.render("ticketing_it.portal_ticket_detail", values)
        except (AccessError, MissingError):
            return request.redirect('/my')

    @http.route(['/my/tickets/new'], type='http', auth="user", website=True)
    def portal_create_ticket(self, **kw):
        """Show create ticket form"""
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if not employee:
            return request.render("ticketing_it.portal_no_employee")

        # FIX: Resolve line manager from employee's parent record
        # employee.parent_id is the manager's hr.employee record;
        # employee.parent_id.user_id is that manager's res.users record.
        line_manager = None
        if employee.parent_id and employee.parent_id.user_id:
            line_manager = employee.parent_id.user_id

        values = {
            'employee': employee,
            'line_manager': line_manager,   # <-- passed to template
            'page_name': 'ticket',
            'error': kw.get('error'),
        }

        return request.render("ticketing_it.portal_create_ticket_form", values)

    @http.route(['/my/tickets/submit'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_submit_ticket(self, **post):
        """Submit new ticket"""
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if not employee:
            return request.redirect('/my')

        try:
            ticket = request.env['it.ticket'].sudo().create({
                'employee_id': employee.id,
                'ticket_type': post.get('ticket_type'),
                'priority': post.get('priority', '1'),
                'subject': post.get('subject'),
                'description': post.get('description'),
                'required_date': post.get('required_date') if post.get('required_date') else False,
            })

            return request.redirect('/my/tickets/%s' % ticket.id)

        except Exception as e:
            _logger.error("Error creating ticket: %s", str(e))
            request.env.cr.rollback()
            return request.redirect('/my/tickets/new?error=1')