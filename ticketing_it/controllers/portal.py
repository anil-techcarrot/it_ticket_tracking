# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class PortalITTicket(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        """Add ticket count to portal homepage"""
        values = super()._prepare_home_portal_values(counters)

        # Always prepare ticket count for portal users
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if employee:
            ticket_count = request.env['it.ticket'].search_count([
                ('employee_id', '=', employee.id)
            ])
            values['ticket_count'] = ticket_count

        return values

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_tickets(self, page=1, sortby=None, **kw):
        """List all tickets for current portal user"""
        # Get current employee
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if not employee:
            return request.render("ticketing_it.portal_no_employee")

        # Search tickets
        domain = [('employee_id', '=', employee.id)]
        ticket_count = request.env['it.ticket'].search_count(domain)

        # Pager
        pager = portal_pager(
            url="/my/tickets",
            total=ticket_count,
            page=page,
            step=10
        )

        # Get tickets
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
        ticket = request.env['it.ticket'].browse(ticket_id)

        # Check access
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

    @http.route(['/my/tickets/new'], type='http', auth="user", website=True)
    def portal_create_ticket(self, **kw):
        """Show create ticket form"""
        employee = request.env['hr.employee'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)

        if not employee:
            return request.render("ticketing_it.portal_no_employee")

        values = {
            'employee': employee,
            'page_name': 'ticket',
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

        # Create ticket
        ticket = request.env['it.ticket'].sudo().create({
            'employee_id': employee.id,
            'ticket_type': post.get('ticket_type'),
            'priority': post.get('priority', '1'),
            'subject': post.get('subject'),
            'description': post.get('description'),
            'required_date': post.get('required_date') if post.get('required_date') else False,
        })

        # Ticket will auto-submit via create method

        return request.redirect('/my/tickets/%s' % ticket.id)