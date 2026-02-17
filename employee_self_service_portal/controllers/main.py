# controllers/main.py
from odoo import http, fields
from odoo.http import request
from .access_helpers import check_portal_access, has_feature_access
import html
import json
import logging

# Set up logger
_logger = logging.getLogger(__name__)

# Constants for model names and URLs
CRM_TAG_MODEL = 'crm.tag'
CRM_REDIRECT_URL = '/my/employee/crm'
HR_EMPLOYEE_MODEL = 'hr.employee'
HR_ATTENDANCE_MODEL = 'hr.attendance'
CRM_LEAD_MODEL = 'crm.lead'
CRM_STAGE_MODEL = 'crm.stage'
MY_EMPLOYEE_URL = '/my/employee'


def get_user_timezone():
    """Get the user's timezone (or fallback to company or UTC)."""
    import pytz
    user_tz = request.env.user.tz or request.env.company.timezone or 'UTC'
    return user_tz


def get_local_datetime(dt=None):
    """Convert UTC datetime to user's local timezone."""
    import pytz
    from datetime import datetime

    if dt is None:
        dt = datetime.now()

    user_tz = get_user_timezone()
    user_pytz = pytz.timezone(user_tz)

    if hasattr(dt, 'tzinfo') and dt.tzinfo:
        return dt.astimezone(user_pytz)
    else:
        utc_dt = dt.replace(tzinfo=pytz.UTC)
        return utc_dt.astimezone(user_pytz)


def _process_tag_ids(post):
    """Refactored to reduce cognitive complexity."""
    tag_ids = []
    if hasattr(post, 'getlist'):
        tag_ids = post.getlist('tag_ids[]') or post.getlist('tag_ids')
    else:
        tag_ids = post.get('tag_ids[]', []) or post.get('tag_ids', [])
        if isinstance(tag_ids, str):
            tag_ids = tag_ids.split(',') if ',' in tag_ids else [tag_ids]
    if not isinstance(tag_ids, list):
        tag_ids = [tag_ids]
    tag_id_list = []
    for tag in tag_ids or []:
        if not tag:
            continue
        try:
            tag_id_list.append(int(tag))
        except (ValueError, TypeError):
            tag_rec = request.env[CRM_TAG_MODEL].sudo().search([('name', '=', tag)], limit=1)
            if not tag_rec:
                tag_rec = request.env[CRM_TAG_MODEL].sudo().create({'name': tag})
            tag_id_list.append(tag_rec.id)
    tag_id_list = [int(t) for t in tag_id_list if t]
    _logger.info('ESS Portal: tag_id_list to write: %s', tag_id_list)
    return tag_id_list


def _process_partner_field(field_value, field_name='partner_id'):
    """Process partner field - handle existing IDs or create new partners."""
    if not field_value:
        return False

    try:
        partner_id = int(field_value)
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if partner.exists():
            return partner_id
    except (ValueError, TypeError):
        pass

    if isinstance(field_value, str) and field_value.strip():
        partner_name = field_value.strip()
        existing_partner = request.env['res.partner'].sudo().search([
            ('name', '=ilike', partner_name),
            ('is_company', '=', True),
        ], limit=1)

        if existing_partner:
            return existing_partner.id

    return False


class PortalEmployee(http.Controller):
    def _get_employee(self):
        # FIX: use request.env.uid instead of deprecated request.uid
        return request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)

    @http.route(MY_EMPLOYEE_URL, type='http', auth='user', website=True)
    def portal_employee_profile(self, **kw):
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        return request.render('employee_self_service_portal.portal_employee_profile_personal', {
            'employee': employee,
            'section': 'personal',
        })

    @http.route(MY_EMPLOYEE_URL + '/attendance/checkin', type='http', auth='user', methods=['POST'], website=True)
    def check_in(self, **post):
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.redirect(MY_EMPLOYEE_URL + '?error=employee_not_found')

        try:
            existing_attendance = request.env[HR_ATTENDANCE_MODEL].sudo().search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False)
            ], limit=1)

            if existing_attendance:
                return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=already_checked_in')

            from datetime import datetime, time
            import pytz

            user_tz = request.env.user.tz or request.env.company.timezone or 'UTC'
            user_pytz = pytz.timezone(user_tz)

            utc_now = datetime.now(pytz.UTC)
            local_now = utc_now.astimezone(user_pytz)
            current_time = local_now.time()

            min_time = time(6, 0)
            max_time = time(23, 0)

            if not (min_time <= current_time <= max_time):
                return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=invalid_time')

            in_latitude = post.get('in_latitude')
            in_longitude = post.get('in_longitude')
            check_in_location = post.get('check_in_location')

            _logger.info("Check-in location data - lat: %s, long: %s, location: %s", in_latitude, in_longitude,
                         check_in_location)
            _logger.info("User timezone: %s, Local time: %s", user_tz, local_now)

            if not check_in_location:
                check_in_location = post.get('location') or 'Check-in from Portal'

            vals = {
                'employee_id': employee.id,
                'check_in': fields.Datetime.now(),
                'check_in_location': check_in_location,
            }

            try:
                if in_latitude:
                    vals['in_latitude'] = float(in_latitude)
                if in_longitude:
                    vals['in_longitude'] = float(in_longitude)
            except (ValueError, TypeError):
                _logger.warning("Invalid latitude/longitude values: %s, %s", in_latitude, in_longitude)

            attendance = request.env[HR_ATTENDANCE_MODEL].sudo().create(vals)
            _logger.info("Check-in successful for employee %s at %s", employee.name, local_now)

            return request.redirect(MY_EMPLOYEE_URL + '/attendance?success=checked_in')

        except Exception as e:
            _logger.error("Check-in failed: %s", e)
            return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=checkin_failed')

    @http.route(MY_EMPLOYEE_URL + '/attendance/quick-checkin', type='http', auth='user', methods=['POST'], website=True,
                csrf=False)
    def quick_check_in(self, **post):
        """Quick check-in from dashboard"""
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.make_response(json.dumps({'status': 'error', 'message': 'Employee not found'}),
                                         headers={'Content-Type': 'application/json'})

        try:
            from datetime import datetime, time
            now = datetime.now()
            current_time = now.time()

            min_time = time(6, 0)
            max_time = time(23, 0)

            if not (min_time <= current_time <= max_time):
                return request.make_response(json.dumps({
                    'status': 'error',
                    'message': 'Check-in not allowed at this time (6 AM - 11 PM only)'
                }), headers={'Content-Type': 'application/json'})

            in_latitude = post.get('in_latitude')
            in_longitude = post.get('in_longitude')
            check_in_location = post.get('check_in_location') or post.get('location') or 'Quick Check-in from Dashboard'

            vals = {
                'employee_id': employee.id,
                'check_in': fields.Datetime.now(),
                'check_in_location': check_in_location,
            }

            try:
                if in_latitude:
                    vals['in_latitude'] = float(in_latitude)
                if in_longitude:
                    vals['in_longitude'] = float(in_longitude)
            except (ValueError, TypeError):
                _logger.warning("Invalid quick check-in latitude/longitude values: %s, %s", in_latitude, in_longitude)

            attendance = request.env[HR_ATTENDANCE_MODEL].sudo().create(vals)
            _logger.info("Quick check-in successful for employee %s at %s", employee.name, now)

            return request.make_response(json.dumps({'status': 'success', 'message': 'Checked in successfully'}),
                                         headers={'Content-Type': 'application/json'})

        except Exception as e:
            _logger.error("Quick check-in failed: %s", e)
            return request.make_response(json.dumps({'status': 'error', 'message': 'Check-in failed'}),
                                         headers={'Content-Type': 'application/json'})

    @http.route(MY_EMPLOYEE_URL + '/attendance/checkout', type='http', auth='user', methods=['POST'], website=True)
    def check_out(self, **post):
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.redirect(MY_EMPLOYEE_URL + '?error=employee_not_found')

        try:
            last_attendance = request.env[HR_ATTENDANCE_MODEL].sudo().search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False)
            ], order='check_in desc', limit=1)

            if not last_attendance:
                return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=no_checkin_found')

            from datetime import datetime, timedelta, time
            import pytz

            user_tz = request.env.user.tz or request.env.company.timezone or 'UTC'
            user_pytz = pytz.timezone(user_tz)

            utc_now = datetime.now(pytz.UTC)
            local_now = utc_now.astimezone(user_pytz)

            check_in_time = fields.Datetime.from_string(last_attendance.check_in)
            check_in_time_local = check_in_time.replace(tzinfo=pytz.UTC).astimezone(user_pytz)

            min_duration = timedelta(minutes=30)
            if (local_now - check_in_time_local) < min_duration:
                return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=minimum_duration_not_met')

            out_latitude = post.get('out_latitude')
            out_longitude = post.get('out_longitude')
            check_out_location = post.get('check_out_location')

            _logger.info("Check-out location data - lat: %s, long: %s, location: %s", out_latitude, out_longitude,
                         check_out_location)
            _logger.info("User timezone: %s, Local time: %s", user_tz, local_now)

            if not check_out_location:
                check_out_location = post.get('location') or 'Check-out from Portal'

            vals = {
                'check_out': fields.Datetime.now(),
                'check_out_location': check_out_location,
                'is_auto_checkout': False,
            }

            try:
                if out_latitude:
                    vals['out_latitude'] = float(out_latitude)
                if out_longitude:
                    vals['out_longitude'] = float(out_longitude)
            except (ValueError, TypeError):
                _logger.warning("Invalid latitude/longitude values: %s, %s", out_latitude, out_longitude)

            last_attendance.sudo().write(vals)
            updated_attendance = request.env[HR_ATTENDANCE_MODEL].sudo().browse(last_attendance.id)
            _logger.info("Check-out successful for employee %s. Worked hours: %s", employee.name,
                         updated_attendance.worked_hours)

            return request.redirect(MY_EMPLOYEE_URL + '/attendance?success=checked_out')

        except Exception as e:
            _logger.error("Check-out failed: %s", e)
            return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=checkout_failed')

    @http.route(MY_EMPLOYEE_URL + '/attendance/quick-checkout', type='http', auth='user', methods=['POST'],
                website=True, csrf=False)
    def quick_check_out(self, **post):
        """Quick check-out from dashboard"""
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.make_response(json.dumps({'status': 'error', 'message': 'Employee not found'}),
                                         headers={'Content-Type': 'application/json'})

        try:
            last_attendance = request.env[HR_ATTENDANCE_MODEL].sudo().search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False)
            ], order='check_in desc', limit=1)

            if not last_attendance:
                return request.make_response(json.dumps({'status': 'error', 'message': 'No active check-in found'}),
                                             headers={'Content-Type': 'application/json'})

            from datetime import datetime, timedelta
            import pytz

            user_tz = request.env.user.tz or request.env.company.timezone or 'UTC'
            user_pytz = pytz.timezone(user_tz)

            utc_now = datetime.now(pytz.UTC)
            local_now = utc_now.astimezone(user_pytz)

            check_in_time = fields.Datetime.from_string(last_attendance.check_in)
            check_in_time_local = check_in_time.replace(tzinfo=pytz.UTC).astimezone(user_pytz)

            min_duration = timedelta(minutes=30)
            if (local_now - check_in_time_local) < min_duration:
                return request.make_response(json.dumps({
                    'status': 'error',
                    'message': 'Minimum work duration not met (30 minutes required)'
                }), headers={'Content-Type': 'application/json'})

            out_latitude = post.get('out_latitude')
            out_longitude = post.get('out_longitude')
            check_out_location = post.get('check_out_location') or post.get(
                'location') or 'Quick Check-out from Dashboard'

            vals = {
                'check_out': fields.Datetime.now(),
                'check_out_location': check_out_location,
                'is_auto_checkout': False,
            }

            try:
                if out_latitude:
                    vals['out_latitude'] = float(out_latitude)
                if out_longitude:
                    vals['out_longitude'] = float(out_longitude)
            except (ValueError, TypeError):
                _logger.warning("Invalid quick check-out latitude/longitude values: %s, %s", out_latitude,
                                out_longitude)

            last_attendance.sudo().write(vals)
            updated_attendance = request.env[HR_ATTENDANCE_MODEL].sudo().browse(last_attendance.id)
            worked_hours = round(updated_attendance.worked_hours, 2)

            return request.make_response(json.dumps({
                'status': 'success',
                'message': 'Checked out successfully. Worked {} hours'.format(worked_hours)
            }), headers={'Content-Type': 'application/json'})

        except Exception as e:
            _logger.error("Quick check-out failed: %s", e)
            return request.make_response(json.dumps({'status': 'error', 'message': 'Check-out failed'}),
                                         headers={'Content-Type': 'application/json'})

    @http.route(MY_EMPLOYEE_URL + '/attendance', type='http', auth='user', website=True)
    @check_portal_access('attendance')
    def portal_attendance_history(self, **kwargs):
        from datetime import datetime
        import pytz

        user_timezone = get_user_timezone()
        user_pytz = pytz.timezone(user_timezone)

        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)

        utc_now = datetime.now(pytz.UTC)
        local_now = utc_now.astimezone(user_pytz)

        month = int(kwargs.get('month', local_now.month))
        year = int(kwargs.get('year', local_now.year))

        domain = [('employee_id', '=', employee.id)]
        if month and year:
            from calendar import monthrange
            # FIX: Use naive datetimes (no tzinfo) in ORM domains
            start_date = datetime(year, month, 1)
            end_date = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
            domain += [('check_in', '>=', start_date.strftime('%Y-%m-%d 00:00:00')),
                       ('check_in', '<=', end_date.strftime('%Y-%m-%d 23:59:59'))]

        attendances = request.env[HR_ATTENDANCE_MODEL].sudo().search(
            domain, order='check_in desc', limit=50)

        today_att = None
        today_str = local_now.strftime('%Y-%m-%d')

        for att in attendances:
            if att.check_in:
                check_in_local = fields.Datetime.context_timestamp(request.env.user, att.check_in)
                if check_in_local.strftime('%Y-%m-%d') == today_str:
                    today_att = att
                    break

        analytics_data = self._get_attendance_analytics(employee, month, year)

        current_year = local_now.year
        years = list(range(current_year - 5, current_year + 2))
        months = [
            {'value': i, 'name': datetime(2000, i, 1).strftime('%B')} for i in range(1, 13)
        ]

        success_message = None
        error_message = None

        if kwargs.get('success') == 'checked_in':
            success_message = "Successfully checked in!"
        elif kwargs.get('success') == 'checked_out':
            success_message = "Successfully checked out!"
        elif kwargs.get('error') == 'already_checked_in':
            error_message = "You are already checked in. Please check out first."
        elif kwargs.get('error') == 'no_checkin_found':
            error_message = "No active check-in found."
        elif kwargs.get('error') == 'invalid_time':
            error_message = "Check-in not allowed at this time (6 AM - 11 PM only). Your local time: {} ({}).".format(
                local_now.strftime('%I:%M %p'), user_timezone)
        elif kwargs.get('error') == 'minimum_duration_not_met':
            error_message = "Minimum work duration not met (30 minutes required)."
        elif kwargs.get('error'):
            error_message = "An error occurred. Please try again."

        return request.render('employee_self_service_portal.portal_attendance', {
            'attendances': attendances,
            'employee': employee,
            'today_att': today_att,
            'selected_month': month,
            'selected_year': year,
            'years': years,
            'months': months,
            'analytics': analytics_data,
            'success_message': success_message,
            'error_message': error_message,
            'user_timezone': user_timezone,
            'format_datetime': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%I:%M %p') if dt else '',
            'format_date': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%d/%m/%Y') if dt else '',
            'format_day': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%A') if dt else '',
        })

    def _get_attendance_analytics(self, employee, month, year):
        """Calculate comprehensive attendance analytics with timezone awareness"""
        from datetime import datetime, timedelta, time
        from calendar import monthrange
        from collections import defaultdict
        import pytz

        user_timezone = get_user_timezone()
        user_pytz = pytz.timezone(user_timezone)

        # FIX: Use naive datetimes for ORM domain queries (convert tz-aware to naive UTC strings)
        start_date_local = datetime(year, month, 1, tzinfo=user_pytz)
        last_day = monthrange(year, month)[1]
        end_date_local = datetime(year, month, last_day, 23, 59, 59, tzinfo=user_pytz)

        # Convert to UTC naive strings for ORM domain
        start_date_utc_naive = start_date_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_date_utc_naive = end_date_local.astimezone(pytz.UTC).replace(tzinfo=None)

        attendances = request.env[HR_ATTENDANCE_MODEL].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(start_date_utc_naive)),
            ('check_in', '<=', fields.Datetime.to_string(end_date_utc_naive)),
        ])

        attendance_by_day = defaultdict(list)
        for att in attendances:
            check_in_local = fields.Datetime.context_timestamp(request.env.user, att.check_in)
            day_key = check_in_local.strftime('%Y-%m-%d')
            attendance_by_day[day_key].append(att)

        total_days = len(attendance_by_day)

        total_hours = 0
        for day, day_attendances in attendance_by_day.items():
            day_hours = sum(att.worked_hours for att in day_attendances if att.worked_hours)
            total_hours += day_hours

        avg_hours = total_hours / total_days if total_days > 0 else 0

        late_threshold = time(9, 30)
        late_arrivals = 0

        for day, day_attendances in attendance_by_day.items():
            day_attendances.sort(key=lambda x: x.check_in)
            first_check_in = fields.Datetime.context_timestamp(request.env.user, day_attendances[0].check_in)
            if first_check_in.time() > late_threshold:
                late_arrivals += 1

        working_days = 0
        current_date = start_date_local.date()
        while current_date <= end_date_local.date():
            if current_date.weekday() < 5:
                working_days += 1
            current_date += timedelta(days=1)

        attendance_percentage = (total_days / working_days * 100) if working_days > 0 else 0

        early_threshold = time(17, 30)
        early_departures = 0

        for day, day_attendances in attendance_by_day.items():
            early_departure = False
            for att in day_attendances:
                if att.check_out:
                    check_out_local = fields.Datetime.context_timestamp(request.env.user, att.check_out)
                    if check_out_local.time() < early_threshold:
                        early_departure = True
                        break
            if early_departure:
                early_departures += 1

        overtime_days = 0
        for day, day_attendances in attendance_by_day.items():
            day_hours = sum(att.worked_hours for att in day_attendances if att.worked_hours)
            if day_hours > 8.5:
                overtime_days += 1

        utc_now = datetime.now(pytz.UTC)
        local_now = utc_now.astimezone(user_pytz)

        week_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local_now.weekday())
        # FIX: Convert to naive UTC string for ORM domain
        week_start_utc_naive = week_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_now_naive = utc_now.replace(tzinfo=None)

        week_attendances = request.env[HR_ATTENDANCE_MODEL].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(week_start_utc_naive)),
            ('check_in', '<=', fields.Datetime.to_string(utc_now_naive)),
        ])

        week_attendance_by_day = defaultdict(list)
        for att in week_attendances:
            check_in_local = fields.Datetime.context_timestamp(request.env.user, att.check_in)
            day_key = check_in_local.strftime('%Y-%m-%d')
            week_attendance_by_day[day_key].append(att)

        this_week_hours = 0
        for day, day_attendances in week_attendance_by_day.items():
            day_hours = sum(att.worked_hours for att in day_attendances if att.worked_hours)
            this_week_hours += day_hours

        return {
            'total_days': total_days,
            'total_hours': round(total_hours, 2),
            'avg_hours': round(avg_hours, 2),
            'working_days': working_days,
            'attendance_percentage': round(attendance_percentage, 1),
            'late_arrivals': late_arrivals,
            'early_departures': early_departures,
            'overtime_days': overtime_days,
            'this_week_hours': round(this_week_hours, 2),
            'month_name': datetime(year, month, 1).strftime('%B %Y')
        }

    @http.route(MY_EMPLOYEE_URL + '/attendance/analytics', type='http', auth='user', website=True)
    def portal_attendance_analytics(self, **kwargs):
        """Dedicated analytics page for attendance"""
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.redirect(MY_EMPLOYEE_URL)

        from datetime import datetime, timedelta
        import pytz

        user_timezone = get_user_timezone()
        user_pytz = pytz.timezone(user_timezone)

        utc_now = datetime.now(pytz.UTC)
        local_now = utc_now.astimezone(user_pytz)

        analytics_months = []
        for i in range(4):
            month_date = local_now.replace(day=1) - timedelta(days=i * 30)
            month_analytics = self._get_attendance_analytics(employee, month_date.month, month_date.year)
            analytics_months.append(month_analytics)

        return request.render('employee_self_service_portal.portal_attendance_analytics', {
            'employee': employee,
            'analytics_months': analytics_months,
            'current_month': analytics_months[0] if analytics_months else {},
            'user_timezone': user_timezone,
            'format_datetime': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%I:%M %p') if dt else '',
            'format_date': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%d/%m/%Y') if dt else '',
            'format_day': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%A') if dt else '',
        })

    @http.route(MY_EMPLOYEE_URL + '/attendance/export', type='http', auth='user', website=True)
    def portal_attendance_export(self, **kwargs):
        """Export attendance data to Excel"""
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.redirect(MY_EMPLOYEE_URL)

        try:
            import io
            import xlsxwriter
            from datetime import datetime, time

            now = datetime.now()
            start_date = kwargs.get('start_date')
            end_date = kwargs.get('end_date')

            if not start_date:
                start_date = now.replace(day=1).strftime('%Y-%m-%d')
            if not end_date:
                from calendar import monthrange
                last_day = monthrange(now.year, now.month)[1]
                end_date = now.replace(day=last_day).strftime('%Y-%m-%d')

            attendances = request.env[HR_ATTENDANCE_MODEL].sudo().search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', start_date + ' 00:00:00'),
                ('check_in', '<=', end_date + ' 23:59:59')
            ], order='check_in desc')

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            worksheet = workbook.add_worksheet('Attendance Report')

            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#4472C4',
                'font_color': 'white',
                'border': 1
            })

            date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
            time_format = workbook.add_format({'num_format': 'hh:mm AM/PM'})
            hours_format = workbook.add_format({'num_format': '0.00'})

            headers = [
                'Date', 'Day', 'Check-In Time', 'Check-In Location',
                'Check-Out Time', 'Check-Out Location', 'Worked Hours', 'Status'
            ]

            for col, header in enumerate(headers):
                worksheet.write(0, col, header, header_format)

            for row, att in enumerate(attendances, 1):
                check_in_date = att.check_in.date() if att.check_in else None
                day_name = att.check_in.strftime('%A') if att.check_in else ''
                check_in_time = att.check_in.time() if att.check_in else None
                check_out_time = att.check_out.time() if att.check_out else None

                status = 'Complete' if att.check_out else 'Active'
                if att.check_in and att.check_in.time() > time(9, 30):
                    status += ' (Late)'
                if att.check_out and att.check_out.time() < time(17, 30):
                    status += ' (Early)'

                worksheet.write(row, 0, check_in_date, date_format)
                worksheet.write(row, 1, day_name)
                worksheet.write(row, 2, check_in_time, time_format)
                worksheet.write(row, 3, att.check_in_location or '')
                worksheet.write(row, 4, check_out_time, time_format)
                worksheet.write(row, 5, att.check_out_location or '')
                worksheet.write(row, 6, att.worked_hours or 0, hours_format)
                worksheet.write(row, 7, status)

            summary_row = len(attendances) + 3
            worksheet.write(summary_row, 0, 'SUMMARY', header_format)
            worksheet.write(summary_row + 1, 0, 'Total Days:')
            worksheet.write(summary_row + 1, 1, len(attendances))
            worksheet.write(summary_row + 2, 0, 'Total Hours:')
            worksheet.write(summary_row + 2, 1, sum(att.worked_hours for att in attendances if att.worked_hours),
                            hours_format)
            worksheet.write(summary_row + 3, 0, 'Average Hours/Day:')
            avg_hours = sum(att.worked_hours for att in attendances if att.worked_hours) / len(
                attendances) if attendances else 0
            worksheet.write(summary_row + 3, 1, avg_hours, hours_format)

            worksheet.set_column('A:A', 12)
            worksheet.set_column('B:B', 10)
            worksheet.set_column('C:C', 15)
            worksheet.set_column('D:D', 30)
            worksheet.set_column('E:E', 15)
            worksheet.set_column('F:F', 30)
            worksheet.set_column('G:G', 12)
            worksheet.set_column('H:H', 15)

            workbook.close()
            output.seek(0)

            filename = "attendance_report_{}_{}_to_{}.xlsx".format(
                employee.name, start_date, end_date
            ).replace(' ', '_').replace('/', '-')

            return request.make_response(
                output.getvalue(),
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', 'attachment; filename="{}"'.format(filename))
                ]
            )

        except Exception as e:
            _logger.error("Attendance export failed: %s", e)
            return request.redirect(MY_EMPLOYEE_URL + '/attendance?error=export_failed')

    @http.route(MY_EMPLOYEE_URL + '/edit', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_edit(self, **post):
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.redirect(MY_EMPLOYEE_URL)
        if http.request.httprequest.method == 'POST':
            vals = {}
            vals['work_email'] = post.get('work_email')
            vals['work_phone'] = post.get('work_phone')
            vals['birthday'] = post.get('birthday')
            vals['gender'] = post.get('gender')
            vals['marital'] = post.get('marital')
            vals['x_experience'] = post.get('x_experience')
            vals['x_skills'] = post.get('x_skills')
            vals['x_certifications'] = post.get('x_certifications')
            vals['x_bank_account'] = post.get('x_bank_account')
            vals['x_bank_name'] = post.get('x_bank_name')
            vals['x_ifsc'] = post.get('x_ifsc')
            vals = {k: v for k, v in vals.items() if v is not None}
            if vals:
                employee.sudo().write(vals)
            return request.redirect(MY_EMPLOYEE_URL)
        return request.render('employee_self_service_portal.portal_employee_edit', {
            'employee': employee,
        })

    @http.route('/my/ess', type='http', auth='user', website=True)
    def portal_ess_dashboard(self, **kwargs):
        return self._render_ess_dashboard('employee_self_service_portal.portal_ess_dashboard_enhanced', **kwargs)

    @http.route('/my/ess/classic', type='http', auth='user', website=True)
    def portal_ess_dashboard_classic(self, **kwargs):
        # Keep the classic view accessible via /my/ess/classic
        return self._render_ess_dashboard('employee_self_service_portal.portal_ess_dashboard', **kwargs)

    @http.route('/my/ess/tickets/new', type='http', auth='user', website=True)
    def portal_ess_ticket_new(self, **kw):
        """Show create ticket form from ESS dashboard"""
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my/ess')

        # FIX: Resolve line manager so the template can display it and
        # disable the submit button when no manager is set.
        # employee.parent_id  → manager's hr.employee record
        # .user_id            → that manager's res.users record (has .name)
        line_manager = None
        if employee.parent_id and employee.parent_id.user_id:
            line_manager = employee.parent_id.user_id

        values = {
            'employee': employee,
            'line_manager': line_manager,  # ← NEW: passed to template
            'page_name': 'ess_dashboard',
            'error': kw.get('error'),
            'error_msg': kw.get('error_msg', ''),
        }
        return request.render('employee_self_service_portal.portal_ess_ticket_form', values)

    @http.route('/my/ess/tickets/submit', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ess_ticket_submit(self, **post):
        """Submit new IT ticket from ESS dashboard"""
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my/ess')

        if not post.get('subject') or not post.get('ticket_type') or not post.get('description'):
            return request.redirect('/my/ess/tickets/new?error=1&error_msg=Please+fill+all+required+fields')

        try:
            ticket = request.env['it.ticket'].sudo().create({
                'employee_id': employee.id,
                'ticket_type': post.get('ticket_type'),
                'priority': post.get('priority', '1'),
                'subject': post.get('subject'),
                'description': post.get('description'),
                'required_date': post.get('required_date') or False,
            })
            _logger.info("IT Ticket %s created from ESS portal by %s", ticket.name, employee.name)
            return request.redirect('/my/ess?ticket_success=1')

        except Exception as e:
            _logger.error("Error creating IT ticket from ESS portal: %s", e)
            request.env.cr.rollback()
            return request.redirect('/my/ess/tickets/new?error=1&error_msg=Failed+to+create+ticket.+Please+try+again.')

    @http.route('/my/ess/enhanced', type='http', auth='user', website=True)
    def portal_ess_dashboard_enhanced(self, **kwargs):
        return self._render_ess_dashboard('employee_self_service_portal.portal_ess_dashboard_enhanced', **kwargs)

    def _render_ess_dashboard(self, template_name, **kwargs):
        """Common method to render dashboard with enhanced data"""
        import pytz

        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)

        dashboard_data = {}

        if employee:
            dashboard_data = self._get_enhanced_dashboard_data(employee)

            dashboard_data.update({
                'has_attendance_access': has_feature_access('attendance'),
                'has_crm_access': has_feature_access('crm'),
                'has_expenses_access': has_feature_access('expenses'),
                'has_payslip_access': has_feature_access('payslip')
            })

        dashboard_data['view_type'] = 'enhanced' if 'enhanced' in template_name else 'standard'

        user_timezone = get_user_timezone()
        dashboard_data.update({
            'user_timezone': user_timezone,
            'format_datetime': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%I:%M %p') if dt else '',
            'format_date': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%d/%m/%Y') if dt else '',
            'format_day': lambda dt: fields.Datetime.context_timestamp(request.env.user, dt).strftime(
                '%A') if dt else '',
        })

        return request.render(template_name, dashboard_data)

    def _get_enhanced_dashboard_data(self, employee):
        """Get comprehensive dashboard data for enhanced view"""
        from datetime import date, datetime, timedelta
        import pytz

        dashboard_data = {'employee': employee}

        payslips = request.env['hr.payslip'].sudo().search([
            ('employee_id', '=', employee.id)
        ])
        payslips_count = len(payslips)

        latest_payslip = request.env['hr.payslip'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid'])
        ], order='date_from desc', limit=1)

        user_timezone = get_user_timezone()
        user_pytz = pytz.timezone(user_timezone)

        utc_now = datetime.now(pytz.UTC)
        local_now = utc_now.astimezone(user_pytz)
        today_local = local_now.date()

        # FIX: Use naive UTC datetimes (strings) for ORM domain queries
        local_day_start = datetime.combine(today_local, datetime.min.time()).replace(tzinfo=user_pytz)
        local_day_end = datetime.combine(today_local, datetime.max.time()).replace(tzinfo=user_pytz)

        utc_day_start_naive = local_day_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_day_end_naive = local_day_end.astimezone(pytz.UTC).replace(tzinfo=None)

        today_attendances = request.env[HR_ATTENDANCE_MODEL].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(utc_day_start_naive)),
            ('check_in', '<=', fields.Datetime.to_string(utc_day_end_naive)),
        ])

        week_start_local = today_local - timedelta(days=today_local.weekday())
        week_end_local = week_start_local + timedelta(days=6)

        week_start_dt = datetime.combine(week_start_local, datetime.min.time()).replace(tzinfo=user_pytz)
        week_end_dt = datetime.combine(week_end_local, datetime.max.time()).replace(tzinfo=user_pytz)

        # FIX: Use naive UTC datetimes (strings) for ORM domain queries
        utc_week_start_naive = week_start_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_week_end_naive = week_end_dt.astimezone(pytz.UTC).replace(tzinfo=None)

        week_attendance = request.env[HR_ATTENDANCE_MODEL].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(utc_week_start_naive)),
            ('check_in', '<=', fields.Datetime.to_string(utc_week_end_naive)),
        ])

        from collections import defaultdict
        week_attendance_by_day = defaultdict(list)
        for att in week_attendance:
            day_key = att.check_in.strftime('%Y-%m-%d')
            week_attendance_by_day[day_key].append(att)

        weekly_hours = 0
        for day, day_attendances in week_attendance_by_day.items():
            day_hours = sum(att.worked_hours for att in day_attendances if att.worked_hours)
            weekly_hours += day_hours

        user = request.env.user
        crm_leads = request.env[CRM_LEAD_MODEL].sudo().search([('user_id', '=', user.id)])
        crm_leads_count = len(crm_leads)

        new_leads = crm_leads.filtered(lambda l: l.stage_id.name in ['New', 'Qualification'] if l.stage_id else False)
        won_leads = crm_leads.filtered(lambda l: l.stage_id.name == 'Won' if l.stage_id else False)
        total_revenue = sum(crm_leads.mapped('expected_revenue'))

        today_dt = datetime.now().date()
        first_day_month = today_dt.replace(day=1)

        current_month_expenses = request.env['hr.expense'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date', '>=', fields.Date.to_string(first_day_month)),
            ('date', '<=', fields.Date.to_string(today_dt)),
        ])

        year_start = today_dt.replace(month=1, day=1)
        ytd_expenses = request.env['hr.expense'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date', '>=', fields.Date.to_string(year_start)),
            ('date', '<=', fields.Date.to_string(today_dt)),
        ])

        expenses_count = len(current_month_expenses)
        current_month_total = sum(current_month_expenses.mapped('total_amount'))
        ytd_total = sum(ytd_expenses.mapped('total_amount'))

        submitted_expenses = current_month_expenses.filtered(lambda x: x.sheet_id and x.sheet_id.state == 'submit')
        approved_expenses = current_month_expenses.filtered(lambda x: x.sheet_id and x.sheet_id.state == 'approve')
        draft_expenses = current_month_expenses.filtered(lambda x: not x.sheet_id or x.sheet_id.state == 'draft')

        expense_stats = {
            'total_count': expenses_count,
            'total_amount': current_month_total,
            'ytd_total': ytd_total,
            'submitted_count': len(submitted_expenses),
            'submitted_amount': sum(submitted_expenses.mapped('total_amount')),
            'approved_count': len(approved_expenses),
            'approved_amount': sum(approved_expenses.mapped('total_amount')),
            'draft_count': len(draft_expenses),
            'draft_amount': sum(draft_expenses.mapped('total_amount')),
            'pending_count': len(submitted_expenses),
        }

        recent_activities = []

        if today_attendances:
            most_recent = today_attendances[0] if len(today_attendances) > 0 else None
            if most_recent:
                recent_activities.append({
                    'type': 'attendance',
                    'title': 'Checked In' if not most_recent.check_out else 'Completed Work Day',
                    'description': 'At {}'.format(most_recent.check_in.strftime(
                        '%I:%M %p')) if not most_recent.check_out else 'Worked {:.2f} hours'.format(
                        most_recent.worked_hours),
                    'time': most_recent.check_in,
                    'icon': 'clock-o',
                    'color': 'primary'
                })

        if crm_leads_count > 0:
            recent_activities.append({
                'type': 'crm',
                'title': 'CRM Active',
                'description': '{} leads to manage'.format(crm_leads_count),
                'time': datetime.now(),
                'icon': 'briefcase',
                'color': 'info'
            })

        if current_month_expenses:
            recent_activities.append({
                'type': 'expense',
                'title': 'Expense Updates',
                'description': '{} expenses this month'.format(len(current_month_expenses)),
                'time': datetime.now(),
                'icon': 'money',
                'color': 'warning'
            })

        recent_activities.sort(key=lambda x: x['time'], reverse=True)

        performance_metrics = {
            'attendance_rate': self._calculate_attendance_rate(employee, today_local),
            'crm_conversion_rate': (len(won_leads) / crm_leads_count * 100) if crm_leads_count > 0 else 0,
            'expense_avg_amount': current_month_total / expenses_count if expenses_count > 0 else 0,
            'weekly_hours': weekly_hours,
            'monthly_targets': self._get_monthly_targets(employee),
        }

        it_tickets_count = 0
        it_tickets_pending = 0
        it_tickets_recent = None
        try:
            it_tickets_count = request.env['it.ticket'].search_count([
                ('employee_id', '=', employee.id)
            ])
            it_tickets_pending = request.env['it.ticket'].search_count([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['draft', 'manager_approval', 'it_approval'])
            ])
            it_tickets_recent = request.env['it.ticket'].search([
                ('employee_id', '=', employee.id)
            ], order='create_date desc', limit=3)
        except Exception:
            pass

        dashboard_data.update({
            'payslips_count': payslips_count,
            'latest_payslip': latest_payslip,
            'today_attendances': today_attendances,
            'weekly_hours': weekly_hours,
            'crm_leads_count': crm_leads_count,
            'crm_analytics': {
                'total_leads': crm_leads_count,
                'new_leads': len(new_leads),
                'won_leads': len(won_leads),
                'total_revenue': total_revenue,
                'conversion_rate': (len(won_leads) / crm_leads_count * 100) if crm_leads_count > 0 else 0
            },
            'expenses_count': expenses_count,
            'expense_stats': expense_stats,
            'recent_activities': recent_activities[:5],
            'performance_metrics': performance_metrics,
            'it_tickets_count': it_tickets_count,
            'it_tickets_pending': it_tickets_pending,
            'it_tickets_recent': it_tickets_recent,
        })

        return dashboard_data

    def _calculate_attendance_rate(self, employee, today_local):
        """Calculate monthly attendance rate using timezone-aware dates"""
        from datetime import datetime, timedelta
        import pytz

        user_timezone = get_user_timezone()
        user_pytz = pytz.timezone(user_timezone)

        first_day_local = today_local.replace(day=1)

        working_days = 0
        current_date = first_day_local
        while current_date <= today_local:
            if current_date.weekday() < 5:
                working_days += 1
            current_date += timedelta(days=1)

        first_day_dt = datetime.combine(first_day_local, datetime.min.time()).replace(tzinfo=user_pytz)
        today_dt_end = datetime.combine(today_local, datetime.max.time()).replace(tzinfo=user_pytz)

        # FIX: Use naive UTC datetimes (strings) for ORM domain queries
        utc_first_day_naive = first_day_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_today_naive = today_dt_end.astimezone(pytz.UTC).replace(tzinfo=None)

        attendance_records = request.env[HR_ATTENDANCE_MODEL].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_string(utc_first_day_naive)),
            ('check_in', '<=', fields.Datetime.to_string(utc_today_naive)),
        ])

        attended_days = set()
        for att in attendance_records:
            local_date = fields.Datetime.context_timestamp(request.env.user, att.check_in).date()
            attended_days.add(local_date)

        return (len(attended_days) / working_days * 100) if working_days > 0 else 0

    def _get_monthly_targets(self, employee):
        """Get monthly targets for the employee"""
        return {
            'attendance_target': 95,
            'crm_leads_target': 10,
            'expense_budget': 2000,
        }

    @http.route(MY_EMPLOYEE_URL + '/personal', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_personal(self, **post):
        employee = self._get_employee()
        if request.httprequest.method == 'POST':
            try:
                vals = {}

                if post.get('work_email'):
                    import re
                    email_pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
                    if re.match(email_pattern, post.get('work_email')):
                        vals['work_email'] = post.get('work_email')
                    else:
                        return request.make_json_response({
                            'success': False,
                            'error': 'Invalid email format'
                        })

                if post.get('work_phone'):
                    vals['work_phone'] = post.get('work_phone')
                if post.get('birthday'):
                    vals['birthday'] = post.get('birthday')
                if post.get('gender'):
                    vals['gender'] = post.get('gender')
                if post.get('marital'):
                    vals['marital'] = post.get('marital')
                if post.get('x_nationality'):
                    vals['x_nationality'] = post.get('x_nationality')
                if post.get('x_emirates_id'):
                    vals['x_emirates_id'] = post.get('x_emirates_id')
                if post.get('x_emirates_expiry'):
                    vals['x_emirates_expiry'] = post.get('x_emirates_expiry')
                if post.get('x_passport_number'):
                    vals['x_passport_number'] = post.get('x_passport_number')
                if post.get('x_passport_country'):
                    vals['x_passport_country'] = post.get('x_passport_country')
                if post.get('x_passport_issue'):
                    vals['x_passport_issue'] = post.get('x_passport_issue')
                if post.get('x_passport_expiry'):
                    vals['x_passport_expiry'] = post.get('x_passport_expiry')
                if post.get('private_email'):
                    vals['private_email'] = post.get('private_email')
                if post.get('private_phone'):
                    vals['private_phone'] = post.get('private_phone')
                if post.get('private_street'):
                    vals['private_street'] = post.get('private_street')
                if post.get('private_street2'):
                    vals['private_street2'] = post.get('private_street2')
                if post.get('private_city'):
                    vals['private_city'] = post.get('private_city')
                if post.get('private_zip'):
                    vals['private_zip'] = post.get('private_zip')
                if post.get('emergency_contact'):
                    vals['emergency_contact'] = post.get('emergency_contact')
                if post.get('emergency_phone'):
                    vals['emergency_phone'] = post.get('emergency_phone')

                employee.sudo().write(vals)
                self._handle_document_uploads(employee, request.httprequest.files)

                return request.make_json_response({
                    'success': True,
                    'message': 'Personal details updated successfully'
                })

            except Exception as e:
                return request.make_json_response({
                    'success': False,
                    'error': str(e)
                })

        return request.render('employee_self_service_portal.portal_employee_profile_personal', {
            'employee': employee,
            'section': 'personal',
        })

    @http.route(MY_EMPLOYEE_URL + '/upload-photo', type='http', auth='user', website=True, methods=['POST'])
    def portal_employee_upload_photo(self, **post):
        """Handle employee photo upload"""
        try:
            employee = self._get_employee()

            photo_file = request.httprequest.files.get('photo')
            if not photo_file:
                return request.make_json_response({
                    'success': False,
                    'error': 'No photo file provided'
                })

            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
            if photo_file.content_type not in allowed_types:
                return request.make_json_response({
                    'success': False,
                    'error': 'Invalid file type. Please upload JPG, PNG, or GIF only.'
                })

            max_size = 5 * 1024 * 1024
            photo_file.seek(0, 2)
            file_size = photo_file.tell()
            photo_file.seek(0)

            if file_size > max_size:
                return request.make_json_response({
                    'success': False,
                    'error': 'File too large. Maximum size is 5MB.'
                })

            import base64
            photo_data = base64.b64encode(photo_file.read())

            employee.sudo().write({'image_1920': photo_data})

            return request.make_json_response({
                'success': True,
                'message': 'Photo uploaded successfully',
                'image_url': '/web/image/hr.employee/{}/image_1920/150x150'.format(employee.id)
            })

        except Exception as e:
            return request.make_json_response({
                'success': False,
                'error': 'Upload failed: {}'.format(str(e))
            })

    @http.route(MY_EMPLOYEE_URL + '/export-pdf', type='http', auth='user', website=True)
    def portal_employee_export_pdf(self, **kwargs):
        """Export employee profile as PDF"""
        try:
            employee = self._get_employee()

            html_content = request.env['ir.qweb']._render('employee_self_service_portal.profile_pdf_template', {
                'employee': employee,
                'company': request.env.company,
            })

            pdf_data = html_content.encode('utf-8')

            return request.make_response(
                pdf_data,
                headers=[
                    ('Content-Type', 'application/pdf'),
                    ('Content-Disposition', 'attachment; filename="profile_{}.pdf"'.format(
                        employee.name.replace(' ', '_')))
                ]
            )

        except Exception as e:
            return request.redirect('/my/employee/personal?error=export_failed')

    def _handle_document_uploads(self, employee, files):
        """Handle document file uploads"""
        try:
            emirates_file = files.get('emirates_id_file')
            if emirates_file and emirates_file.filename:
                self._save_employee_document(employee, emirates_file, 'Emirates ID')

            passport_file = files.get('passport_file')
            if passport_file and passport_file.filename:
                self._save_employee_document(employee, passport_file, 'Passport')

            other_files = files.getlist('other_documents')
            for file in other_files:
                if file and file.filename:
                    self._save_employee_document(employee, file, 'Other Document')

        except Exception as e:
            _logger.error("Error handling document uploads: %s", str(e))

    def _save_employee_document(self, employee, file, doc_type):
        """Save individual document file"""
        try:
            import base64

            max_size = 10 * 1024 * 1024
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)

            if file_size > max_size:
                return

            file_data = base64.b64encode(file.read())

            attachment = request.env['ir.attachment'].sudo().create({
                'name': '{} - {}'.format(doc_type, file.filename),
                'datas': file_data,
                'res_model': 'hr.employee',
                'res_id': employee.id,
                'public': False,
                'type': 'binary',
            })

            return attachment

        except Exception as e:
            _logger.error("Error saving document %s: %s", file.filename, str(e))
            return None

    @http.route(MY_EMPLOYEE_URL + '/experience', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_experience(self, **post):
        employee = self._get_employee()
        if request.httprequest.method == 'POST':
            try:
                vals = {}

                experience = post.get('x_experience', '').strip()
                if experience:
                    word_count = len(experience.split())
                    if word_count < 10:
                        return request.make_json_response({
                            'success': False,
                            'error': 'Experience description should be at least 10 words.'
                        })
                    vals['x_experience'] = experience

                skills = post.get('x_skills', '').strip()
                if skills:
                    skills_list = [skill.strip() for skill in skills.split(',') if skill.strip()]
                    if len(skills_list) < 3:
                        return request.make_json_response({
                            'success': False,
                            'error': 'Please add at least 3 skills.'
                        })
                    vals['x_skills'] = ', '.join(skills_list)

                employee.sudo().write(vals)
                self._handle_experience_documents(employee, request.httprequest.files)

                return request.make_json_response({
                    'success': True,
                    'message': 'Experience and skills updated successfully'
                })

            except Exception as e:
                return request.make_json_response({
                    'success': False,
                    'error': str(e)
                })

        return request.render('employee_self_service_portal.portal_employee_profile_experience', {
            'employee': employee,
            'section': 'experience',
        })

    def _handle_experience_documents(self, employee, files):
        """Handle experience-related document uploads"""
        try:
            resume_file = files.get('resume_file')
            if resume_file and resume_file.filename:
                self._save_employee_document(employee, resume_file, 'Resume/CV')

            training_files = files.getlist('training_certificates')
            for file in training_files:
                if file and file.filename:
                    self._save_employee_document(employee, file, 'Training Certificate')

            award_files = files.getlist('awards_files')
            for file in award_files:
                if file and file.filename:
                    self._save_employee_document(employee, file, 'Award/Recognition')

        except Exception as e:
            _logger.error("Error handling experience documents: %s", str(e))

    @http.route(MY_EMPLOYEE_URL + '/certification', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_certification(self, **post):
        employee = self._get_employee()
        if request.httprequest.method == 'POST':
            vals = {'x_certifications': post.get('x_certifications')}
            employee.sudo().write({k: v for k, v in vals.items() if v is not None})
        return request.render('employee_self_service_portal.portal_employee_profile_certification', {
            'employee': employee,
            'section': 'certification',
        })

    @http.route(MY_EMPLOYEE_URL + '/bank', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_bank(self, **post):
        employee = self._get_employee()
        if request.httprequest.method == 'POST':
            vals = {
                'x_bank_account': post.get('x_bank_account'),
                'x_bank_name': post.get('x_bank_name'),
                'x_ifsc': post.get('x_ifsc'),
            }
            employee.sudo().write({k: v for k, v in vals.items() if v is not None})
        return request.render('employee_self_service_portal.portal_employee_profile_bank', {
            'employee': employee,
            'section': 'bank',
        })

    @http.route('/my/employee/crm', type='http', auth='user', website=True)
    @check_portal_access('crm')
    def portal_employee_crm(self, **kwargs):
        employee = self._get_employee()
        user = request.env.user

        domain = [('user_id', '=', user.id)]

        stage_filter = kwargs.get('stage')
        if stage_filter:
            domain.append(('stage_id', '=', int(stage_filter)))

        practice_filter = kwargs.get('practice')
        if practice_filter:
            lead_model = request.env['crm.lead']
            if 'practice_id' in lead_model._fields:
                domain.append(('practice_id', '=', int(practice_filter)))

        industry_filter = kwargs.get('industry')
        if industry_filter:
            lead_model = request.env['crm.lead']
            if 'industry_id' in lead_model._fields:
                domain.append(('industry_id', '=', int(industry_filter)))

        priority_filter = kwargs.get('priority')
        if priority_filter:
            domain.append(('priority', '=', priority_filter))

        date_from = kwargs.get('date_from')
        if date_from:
            domain.append(('create_date', '>=', date_from + ' 00:00:00'))

        date_to = kwargs.get('date_to')
        if date_to:
            domain.append(('create_date', '<=', date_to + ' 23:59:59'))

        activity_due_from = kwargs.get('activity_due_from')
        if activity_due_from:
            domain.append(('activity_ids.date_deadline', '>=', activity_due_from))

        activity_due_to = kwargs.get('activity_due_to')
        if activity_due_to:
            domain.append(('activity_ids.date_deadline', '<=', activity_due_to))

        quick_activity = kwargs.get('quick_activity')
        if quick_activity:
            from datetime import date, timedelta
            today = date.today()

            if quick_activity == 'today':
                domain.append(('activity_ids.date_deadline', '=', today))
            elif quick_activity == 'yesterday':
                yesterday = today - timedelta(days=1)
                domain.append(('activity_ids.date_deadline', '=', yesterday))
            elif quick_activity == 'tomorrow':
                tomorrow = today + timedelta(days=1)
                domain.append(('activity_ids.date_deadline', '=', tomorrow))
            elif quick_activity == 'past':
                domain.append(('activity_ids.date_deadline', '<', today))
            elif quick_activity == 'future':
                domain.append(('activity_ids.date_deadline', '>', today))
            elif quick_activity == 'this_week':
                monday = today - timedelta(days=today.weekday())
                sunday = monday + timedelta(days=6)
                domain.append(('activity_ids.date_deadline', '>=', monday))
                domain.append(('activity_ids.date_deadline', '<=', sunday))
            elif quick_activity == 'overdue':
                domain.append(('activity_ids.date_deadline', '<', today))
            elif quick_activity == 'no_activities':
                domain.append(('activity_ids', '=', False))

        tags_filter = kwargs.get('tags')
        if tags_filter:
            try:
                if isinstance(tags_filter, str):
                    tag_ids = [int(tags_filter)]
                else:
                    tag_ids = [int(tag) for tag in tags_filter if tag]

                if tag_ids:
                    lead_model = request.env['crm.lead']
                    if 'tag_ids' in lead_model._fields:
                        domain.append(('tag_ids', 'in', tag_ids))
            except (ValueError, TypeError):
                pass

        leads = request.env['crm.lead'].sudo().search(domain, order='priority desc, create_date desc')

        from datetime import date
        today = date.today()

        def get_next_activity_date(lead):
            if not lead.activity_ids:
                return date.max
            next_activity = lead.activity_ids.sorted('date_deadline')
            if next_activity and next_activity[0].date_deadline:
                activity_date = next_activity[0].date_deadline
                if hasattr(activity_date, 'date'):
                    return activity_date.date()
                return activity_date
            return date.max

        leads = leads.sorted(key=lambda lead: (
            get_next_activity_date(lead),
            -int(lead.priority or '0'),
            -lead.id
        ))

        all_user_leads = request.env['crm.lead'].sudo().search([('user_id', '=', user.id)])
        stages = request.env['crm.stage'].sudo().search([], order='sequence, name')

        practices = []
        try:
            if 'practice_id' in all_user_leads._fields:
                practice_model = None
                for model_name in ['x_practice', 'crm.practice', 'practice', 'x_crm_practice']:
                    try:
                        practice_model = request.env[model_name]
                        break
                    except KeyError:
                        continue

                if practice_model:
                    practices = practice_model.sudo().search([], order='name')
        except Exception:
            practices = []

        industries = []
        try:
            if 'industry_id' in all_user_leads._fields:
                industries = request.env['res.partner.industry'].sudo().search([], order='name')
        except Exception:
            industries = []

        tags = []
        try:
            if 'tag_ids' in all_user_leads._fields:
                tags = request.env['crm.tag'].sudo().search([], order='name')
        except Exception:
            tags = []

        processed_leads = []
        for lead in leads:
            lead_data = {
                'record': lead,
                'activity_summary': self._get_activity_summary(lead),
                'next_activity_info': self._get_next_activity_info(lead, today),
                'recent_note_info': self._get_recent_note_info(lead),
            }
            processed_leads.append(lead_data)

        view_type = kwargs.get('view', 'list')
        template_name = 'employee_self_service_portal.portal_employee_crm_enhanced' if view_type == 'enhanced' else 'employee_self_service_portal.portal_employee_crm'

        dashboard_kpis = {}
        if view_type == 'enhanced':
            all_user_leads_current = request.env['crm.lead'].sudo().search([('user_id', '=', user.id)])
            dashboard_kpis = self._calculate_dashboard_kpis(all_user_leads_current, today)

        return request.render(template_name, {
            'employee': employee,
            'leads': leads,
            'processed_leads': processed_leads,
            'stages': stages,
            'filter_stages': stages,
            'filter_practices': practices,
            'filter_industries': industries,
            'filter_tags': tags,
            'dashboard_kpis': dashboard_kpis,
            'view_type': view_type,
            'current_filters': {
                'stage': stage_filter or '',
                'practice': practice_filter or '',
                'industry': industry_filter or '',
                'priority': priority_filter or '',
                'date_from': date_from or '',
                'date_to': date_to or '',
                'activity_due_from': activity_due_from or '',
                'activity_due_to': activity_due_to or '',
                'quick_activity': quick_activity or '',
                'tags': tags_filter or '',
                'view': view_type,
            }
        })

    def _get_activity_summary(self, lead):
        activity_count = len(lead.activity_ids)
        return {
            'count': activity_count,
            'has_activities': activity_count > 0
        }

    def _get_next_activity_info(self, lead, today):
        if not lead.activity_ids:
            return {'has_activity': False}

        next_activity = lead.activity_ids.sorted('date_deadline')[0]
        activity_date = next_activity.date_deadline

        if not activity_date:
            return {
                'has_activity': True,
                'activity_type': next_activity.activity_type_id.name,
                'user_name': next_activity.user_id.name,
                'relative_date': 'No date',
                'badge_class': 'badge-secondary'
            }

        if hasattr(activity_date, 'date'):
            activity_date = activity_date.date()

        date_diff = (activity_date - today).days

        if date_diff == 0:
            relative_date = 'Today'
            badge_class = 'badge-warning'
        elif date_diff == 1:
            relative_date = 'Tomorrow'
            badge_class = 'badge-info'
        elif date_diff == -1:
            relative_date = 'Yesterday'
            badge_class = 'badge-danger'
        elif date_diff < 0:
            relative_date = 'Overdue {} days'.format(abs(date_diff))
            badge_class = 'badge-danger'
        else:
            relative_date = 'Due in {} days'.format(date_diff)
            badge_class = 'badge-info'

        return {
            'has_activity': True,
            'activity_type': next_activity.activity_type_id.name,
            'user_name': next_activity.user_id.name,
            'relative_date': relative_date,
            'badge_class': badge_class
        }

    def _get_recent_note_info(self, lead):
        import re

        recent_notes = lead.message_ids.filtered(
            lambda m: m.message_type == 'comment' and m.body and m.body.strip()
        )

        if not recent_notes:
            return {'has_note': False}

        recent_note = recent_notes[0]
        clean_body = re.sub(r'<[^>]+>', '', recent_note.body or '').strip()

        if len(clean_body) > 47:
            clean_body = clean_body[:47] + '...'

        date_str = ''
        if recent_note.date:
            date_str = recent_note.date.strftime('%m/%d %H:%M')

        return {
            'has_note': True,
            'author_name': recent_note.author_id.name or 'System',
            'date_str': date_str,
            'clean_body': clean_body,
            'full_body': recent_note.body or ''
        }

    def _calculate_dashboard_kpis(self, leads, today):
        from datetime import timedelta

        total_leads = len(leads)

        new_leads = leads.filtered(lambda l: l.stage_id.name in ['New', 'Qualification'] if l.stage_id else False)
        in_progress_leads = leads.filtered(
            lambda l: l.stage_id.name in ['Qualified', 'Proposition'] if l.stage_id else False)
        won_leads = leads.filtered(lambda l: l.stage_id.name == 'Won' if l.stage_id else False)

        total_revenue = sum(leads.mapped('expected_revenue'))
        won_revenue = sum(won_leads.mapped('expected_revenue'))

        overdue_activities = 0
        today_activities = 0

        for lead in leads:
            for activity in lead.activity_ids:
                if activity.date_deadline:
                    activity_date = activity.date_deadline
                    if hasattr(activity_date, 'date'):
                        activity_date = activity_date.date()

                    if activity_date < today:
                        overdue_activities += 1
                    elif activity_date == today:
                        today_activities += 1

        conversion_rate = (len(won_leads) / total_leads * 100) if total_leads > 0 else 0

        return {
            'total_leads': total_leads,
            'new_leads': len(new_leads),
            'in_progress_leads': len(in_progress_leads),
            'won_leads': len(won_leads),
            'total_revenue': total_revenue,
            'won_revenue': won_revenue,
            'overdue_activities': overdue_activities,
            'today_activities': today_activities,
            'conversion_rate': round(conversion_rate, 1),
        }

    @http.route('/my/employee/crm/create', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_crm_create(self, **post):
        user = request.env.user
        if request.httprequest.method == 'POST':
            partner_id = _process_partner_field(post.get('partner_id'), 'partner_id')
            point_of_contact_id = _process_partner_field(post.get('point_of_contact_id'), 'point_of_contact_id')

            vals = {
                'name': post.get('name'),
                'partner_id': partner_id,
                'email_from': post.get('email_from'),
                'phone': post.get('phone'),
                'expected_revenue': post.get('expected_revenue') or 0.0,
                'user_id': user.id,
                'stage_id': post.get('stage_id') or False,
                'description': post.get('description'),
                'probability': post.get('probability') or 0.0,
                'date_deadline': post.get('date_deadline') or False,
                'point_of_contact_id': point_of_contact_id,
                'practice_id': post.get('practice_id') or False,
                'deal_manager_id': post.get('deal_manager_id') or False,
                'client_proposal_submission_date': post.get('client_proposal_submission_date') or False,
                'proposal_submitted_date': post.get('proposal_submitted_date') or False,
                'engaged_presales': bool(post.get('engaged_presales')),
                'industry_id': post.get('industry_id') or False,
                'type_id': post.get('type_id') or False,
            }
            lead = request.env['crm.lead'].sudo().create(vals)
            tag_id_list = _process_tag_ids(post)
            lead.sudo().write({'tag_ids': [(6, 0, tag_id_list)]})
            return request.redirect(CRM_REDIRECT_URL)
        partners = request.env['res.partner'].sudo().search([('active', '=', True), ('is_company', '=', True)])
        contacts = request.env['res.partner'].sudo().search([('is_company', '=', False)])
        stages = request.env['crm.stage'].sudo().search([])
        all_tags = request.env[CRM_TAG_MODEL].sudo().search([])
        salespersons = request.env['hr.employee'].sudo().search([('active', '=', True)])
        practices = request.env['crm.practice'].sudo().search([('active', '=', True)])
        industries = request.env['crm.industry'].sudo().search([('active', '=', True)])
        lead_types = request.env['crm.lead.type'].sudo().search([('active', '=', True)])
        employees = request.env['hr.employee'].sudo().search([('active', '=', True)])
        current_user_id = request.env.user.id
        return request.render('employee_self_service_portal.portal_employee_crm_create', {
            'partners': partners,
            'contacts': contacts,
            'stages': stages,
            'all_tags': all_tags,
            'salespersons': salespersons,
            'practices': practices,
            'industries': industries,
            'lead_types': lead_types,
            'employees': employees,
            'current_user_id': current_user_id,
        })

    @http.route('/my/employee/crm/edit/<int:lead_id>', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_employee_crm_edit(self, lead_id, **post):
        lead = request.env[CRM_LEAD_MODEL].sudo().browse(lead_id)
        user = request.env.user
        if not lead or lead.user_id.id != user.id:
            return request.redirect(CRM_REDIRECT_URL)
        if request.httprequest.method == 'POST':
            point_of_contact_id = _process_partner_field(post.get('point_of_contact_id'), 'point_of_contact_id')

            vals = {
                'name': post.get('name'),
                'email_from': post.get('email_from'),
                'phone': post.get('phone'),
                'description': post.get('description'),
                'date_deadline': post.get('date_deadline'),
                'point_of_contact_id': point_of_contact_id,
                'practice_id': post.get('practice_id') or False,
                'deal_manager_id': post.get('deal_manager_id') or False,
                'client_proposal_submission_date': post.get('client_proposal_submission_date') or False,
                'proposal_submitted_date': post.get('proposal_submitted_date') or False,
                'engaged_presales': bool(post.get('engaged_presales')),
                'industry_id': post.get('industry_id') or False,
                'type_id': post.get('type_id') or False,
            }
            prob = post.get('probability')
            if prob:
                try:
                    vals['probability'] = float(prob)
                except Exception:
                    pass
            exp_rev = post.get('expected_revenue')
            if exp_rev:
                try:
                    vals['expected_revenue'] = float(exp_rev)
                except Exception:
                    pass
            stage_id = post.get('stage_id')
            if stage_id:
                try:
                    stage_id_int = int(stage_id)
                    stage = request.env[CRM_STAGE_MODEL].sudo().browse(stage_id_int)
                    if stage.exists():
                        vals['stage_id'] = stage_id_int
                except Exception:
                    pass
            lead.sudo().write({k: v for k, v in vals.items() if v is not None})
            tag_id_list = _process_tag_ids(post)
            lead.sudo().write({'tag_ids': [(6, 0, tag_id_list)]})
            return request.redirect(CRM_REDIRECT_URL)
        stages = request.env[CRM_STAGE_MODEL].sudo().search([])
        partners = request.env['res.partner'].sudo().search([])
        contacts = request.env['res.partner'].sudo().search([('is_company', '=', False)])
        all_tags = request.env[CRM_TAG_MODEL].sudo().search([])
        salespersons = request.env['res.users'].sudo().search([('active', '=', True)])
        practices = request.env['crm.practice'].sudo().search([('active', '=', True)])
        industries = request.env['crm.industry'].sudo().search([('active', '=', True)])
        lead_types = request.env['crm.lead.type'].sudo().search([('active', '=', True)])
        employees = request.env['hr.employee'].sudo().search([('active', '=', True)])
        activity_types = request.env['mail.activity.type'].sudo().search([])
        default_activity_type_id = request.env.ref('mail.mail_activity_data_todo').id if request.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False) else (
                    activity_types and activity_types[0].id or False)
        return request.render('employee_self_service_portal.portal_employee_crm_edit', {
            'lead': lead,
            'stages': stages,
            'all_tags': all_tags,
            'partners': partners,
            'contacts': contacts,
            'salespersons': salespersons,
            'practices': practices,
            'industries': industries,
            'lead_types': lead_types,
            'employees': employees,
            'activity_types': activity_types,
            'default_activity_type_id': default_activity_type_id,
        })

    @http.route('/my/employee/crm/delete/<int:lead_id>', type='http', auth='user', website=True, methods=['POST'])
    def portal_employee_crm_delete(self, lead_id, **post):
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user
        if lead and lead.user_id.id == user.id:
            lead.sudo().unlink()
        return request.redirect('/my/employee/crm')

    @http.route('/my/employee/crm/log_note/<int:lead_id>', type='http', auth='user', website=True, methods=['POST'])
    def portal_employee_crm_log_note(self, lead_id, **post):
        lead = request.env[CRM_LEAD_MODEL].sudo().browse(lead_id)
        user = request.env.user
        note = post.get('note')
        file_keys = list(request.httprequest.files.keys())
        _logger.info('ESS Portal: Received file keys: %s', file_keys)
        files = []
        if hasattr(request.httprequest.files, 'getlist'):
            files = request.httprequest.files.getlist('attachments')
        elif 'attachments' in request.httprequest.files:
            file = request.httprequest.files['attachments']
            if file:
                files = [file]
        _logger.info('ESS Portal: Number of files in attachments: %s', len(files))
        if lead and (note or files) and lead.user_id.id == user.id:
            msg = lead.message_post(body=note or '', message_type='comment', author_id=user.partner_id.id)
            import base64
            attachment_ids = []
            for file in files:
                try:
                    file.seek(0)
                except Exception:
                    pass
                file_content = file.read()
                if file_content:
                    if isinstance(file_content, str):
                        file_content = file_content.encode('utf-8')
                    encoded_content = base64.b64encode(file_content).decode('utf-8')
                    attachment = request.env['ir.attachment'].sudo().create({
                        'name': file.filename,
                        'datas': encoded_content,
                        'res_model': 'crm.lead',
                        'res_id': lead.id,
                        'mimetype': file.mimetype,
                        'type': 'binary',
                        'public': True,
                    })
                    attachment_ids.append(attachment.id)
                    _logger.info('ESS Portal: Created attachment id=%s name=%s', attachment.id, attachment.name)
            if attachment_ids:
                msg.sudo().write({'attachment_ids': [(4, att_id) for att_id in attachment_ids]})
        return request.redirect('/my/employee/crm/edit/{}'.format(lead_id))

    @http.route('/my/employee/crm/add_activity/<int:lead_id>', type='http', auth='user', website=True, methods=['POST'])
    def portal_employee_crm_add_activity(self, lead_id, **post):
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user
        summary = post.get('summary')
        date_deadline = post.get('date_deadline')
        note = post.get('note')
        activity_type_id = post.get('activity_type_id')
        assigned_user_id = post.get('assigned_user_id')
        if lead and summary and date_deadline and lead.user_id.id == user.id:
            activity_type_xmlid = None
            activity_type_name = ''
            if activity_type_id:
                activity_type = request.env['mail.activity.type'].sudo().browse(int(activity_type_id))
                external_ids = activity_type.get_external_id()
                activity_type_xmlid = external_ids.get(activity_type.id)
                activity_type_name = activity_type.name
            if not activity_type_xmlid:
                activity_type_xmlid = 'mail.mail_activity_data_todo'
                activity_type_name = 'To Do'
            assigned_uid = int(assigned_user_id) if assigned_user_id else user.id
            assigned_user = request.env['res.users'].sudo().browse(assigned_uid)
            lead.activity_schedule(
                activity_type_xmlid,
                summary=summary,
                note=note,
                date_deadline=date_deadline,
                user_id=assigned_uid
            )
            msg = "Activity created: <b>{}</b> - <b>{}</b> (Assigned to: {}, Due: {})".format(
                activity_type_name, summary, assigned_user.name, date_deadline)
            if note:
                msg += "<br/>Note: {}".format(html.escape(note))
            lead.message_post(body=msg)

        referer = request.httprequest.environ.get('HTTP_REFERER', '')
        if 'activity_modal' in referer or post.get('from_modal'):
            return request.redirect('/my/employee/crm')
        else:
            return request.redirect('/my/employee/crm/edit/{}'.format(lead_id))

    @http.route('/my/employee/crm/activity_done/<int:activity_id>', type='http', auth='user', website=True,
                methods=['POST'])
    def portal_employee_crm_activity_done(self, activity_id, **post):
        activity = request.env['mail.activity'].sudo().browse(activity_id)
        lead_id = int(request.params.get('lead_id', 0))
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user
        if activity and lead and lead.user_id.id == user.id and activity.res_model == 'crm.lead' and activity.res_id == lead.id:
            try:
                activity.action_done()
            except Exception:
                pass

        referer = request.httprequest.environ.get('HTTP_REFERER', '')
        if 'activity_modal' in referer or post.get('from_modal'):
            return request.redirect('/my/employee/crm')
        else:
            return request.redirect('/my/employee/crm/edit/{}'.format(lead_id))

    @http.route('/my/employee/crm/activity_edit/<int:activity_id>', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_employee_crm_activity_edit(self, activity_id, **post):
        activity = request.env['mail.activity'].sudo().browse(activity_id)
        lead_id = int(request.params.get('lead_id', 0))
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user
        if not (
                activity and lead and lead.user_id.id == user.id and activity.res_model == 'crm.lead' and activity.res_id == lead.id):
            return request.redirect('/my/employee/crm/edit/{}'.format(lead_id))
        if request.httprequest.method == 'POST':
            vals = {}
            if post.get('summary') is not None:
                vals['summary'] = post.get('summary')
            if post.get('date_deadline') is not None:
                vals['date_deadline'] = post.get('date_deadline')
            if post.get('note') is not None:
                vals['note'] = post.get('note')
            if post.get('activity_type_id'):
                vals['activity_type_id'] = int(post.get('activity_type_id'))
            if post.get('user_id'):
                vals['user_id'] = int(post.get('user_id'))
            if vals:
                activity.sudo().write(vals)
                activity_type_name = activity.activity_type_id.name or ''
                assigned_user = activity.user_id
                msg = "Activity updated: <b>{}</b> - <b>{}</b> (Assigned to: {}, Due: {})".format(
                    activity_type_name, activity.summary, assigned_user.name, activity.date_deadline)
                if activity.note:
                    msg += "<br/>Note: {}".format(html.escape(activity.note))
                lead.message_post(body=msg)
            return request.redirect('/my/employee/crm/edit/{}'.format(lead_id))
        activity_types = request.env['mail.activity.type'].sudo().search([])
        salespersons = request.env['res.users'].sudo().search([('active', '=', True)])
        return request.render('employee_self_service_portal.portal_employee_crm_activity_edit', {
            'activity': activity,
            'lead': lead,
            'activity_types': activity_types,
            'salespersons': salespersons,
        })

    @http.route('/my/employee/crm/activity_delete/<int:activity_id>', type='http', auth='user', website=True,
                methods=['POST'])
    def portal_employee_crm_activity_delete(self, activity_id, **post):
        activity = request.env['mail.activity'].sudo().browse(activity_id)
        lead_id = int(request.params.get('lead_id', 0))
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user
        if activity and lead and lead.user_id.id == user.id and activity.res_model == 'crm.lead' and activity.res_id == lead.id:
            try:
                activity_type_name = activity.activity_type_id.name or ''
                summary = activity.summary or ''
                assigned_user = activity.user_id
                due = activity.date_deadline or ''
                note = activity.note or ''
                msg = "Activity deleted: <b>{}</b> - <b>{}</b> (Assigned to: {}, Due: {})".format(
                    activity_type_name, summary, assigned_user.name, due)
                if note:
                    msg += "<br/>Note: {}".format(html.escape(note))
                activity.sudo().unlink()
                lead.message_post(body=msg)
            except Exception:
                pass

        referer = request.httprequest.environ.get('HTTP_REFERER', '')
        if 'activity_modal' in referer or post.get('from_modal'):
            return request.redirect('/my/employee/crm')
        else:
            return request.redirect('/my/employee/crm/edit/{}'.format(lead_id))

    @http.route('/my/employee/crm/activity_modal/<int:lead_id>/<string:action>', type='http', auth='user', website=True)
    def portal_employee_crm_activity_modal(self, lead_id, action, **kwargs):
        """Route to handle activity modal content loading"""
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user

        if not lead or lead.user_id.id != user.id:
            return '<div class="alert alert-danger">Access denied</div>'

        activity_types = request.env['mail.activity.type'].sudo().search([])
        default_activity_type_id = request.env.ref('mail.mail_activity_data_todo').id if request.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False) else (
                    activity_types and activity_types[0].id or False)
        salespersons = request.env['res.users'].sudo().search([('active', '=', True)])

        from datetime import date
        today = date.today()

        context = {
            'lead': lead,
            'activity_types': activity_types,
            'default_activity_type_id': default_activity_type_id,
            'salespersons': salespersons,
            'today': today,
        }

        if action == 'view':
            return request.render('employee_self_service_portal.portal_employee_crm_activity_modal_view', context)
        elif action == 'add':
            return request.render('employee_self_service_portal.portal_employee_crm_activity_modal_add', context)
        else:
            return '<div class="alert alert-danger">Invalid action</div>'

    def _validate_expense_data(self, post):
        """Validate expense submission data"""
        errors = []

        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        currency_symbol = employee.company_id.currency_id.symbol or '$'

        required_fields = {
            'name': 'Description',
            'date': 'Date',
            'total_amount': 'Amount',
            'category_id': 'Category'
        }

        for field, label in required_fields.items():
            if not post.get(field):
                errors.append('{} is required.'.format(label))

        try:
            amount = float(post.get('total_amount', 0))
            if amount <= 0:
                errors.append('Amount must be greater than 0.')
            elif amount > 50000:
                errors.append('Amount cannot exceed {}50,000.'.format(currency_symbol))
        except (ValueError, TypeError):
            errors.append('Amount must be a valid number.')

        if post.get('date'):
            try:
                from datetime import datetime
                expense_date = datetime.strptime(post.get('date'), '%Y-%m-%d').date()
                today = datetime.now().date()
                if expense_date > today:
                    errors.append('Expense date cannot be in the future.')
            except ValueError:
                errors.append('Invalid date format.')

        if post.get('date') and post.get('total_amount') and post.get('category_id'):
            try:
                # FIX: use request.env.uid instead of deprecated request.uid
                employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
                existing_expense = request.env['hr.expense'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('date', '=', post.get('date')),
                    ('total_amount', '=', float(post.get('total_amount'))),
                    ('product_id', '=', int(post.get('category_id'))),
                    ('sheet_id.state', '!=', 'cancel')
                ], limit=1)

                if existing_expense:
                    errors.append(
                        'A similar expense already exists for the same date, amount, and category. Please verify this is not a duplicate.')
                    _logger.warning("Potential duplicate expense detected for employee %s", employee.name)

            except Exception as duplicate_check_error:
                _logger.warning("Error checking for duplicate expenses: %s", str(duplicate_check_error))

        attachment = request.httprequest.files.get('attachment')
        if attachment and attachment.filename:
            file_content = attachment.read()
            if len(file_content) > 10 * 1024 * 1024:
                errors.append('File size cannot exceed 10MB.')
            attachment.seek(0)

            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf']
            if attachment.content_type not in allowed_types:
                errors.append('Only JPG, PNG, and PDF files are allowed.')

        return errors

    def _get_or_create_expense_sheet(self, employee, expense):
        """Get existing draft sheet or create new one"""
        company_id = employee.company_id.id

        sheet = request.env['hr.expense.sheet'].sudo().search([
            ('employee_id', '=', employee.id),
            ('company_id', '=', company_id),
            ('state', '=', 'draft')
        ], limit=1)

        if not sheet:
            sheet_vals = {
                'name': 'Expense Report - {}'.format(employee.name),
                'employee_id': employee.id,
                'expense_line_ids': [(4, expense.id)],
                'company_id': company_id,
                'currency_id': employee.company_id.currency_id.id,
            }
            sheet = request.env['hr.expense.sheet'].sudo().create(sheet_vals)
            _logger.info("Created new expense sheet with ID: %d", sheet.id)
        else:
            sheet.write({'expense_line_ids': [(4, expense.id)]})
            _logger.info("Added expense to existing sheet ID: %d", sheet.id)

        if sheet.state == 'draft' and sheet.expense_line_ids:
            try:
                sheet.action_submit_sheet()
                _logger.info("Successfully submitted expense sheet ID: %d", sheet.id)
            except Exception as submit_error:
                _logger.warning("Failed to auto-submit sheet: %s", str(submit_error))

        return sheet

    @http.route(MY_EMPLOYEE_URL + '/payslips', type='http', auth='user', website=True)
    @check_portal_access('payslip')
    def portal_payslip_history(self, **kwargs):
        """Portal route for viewing payslip history - Only confirmed payslips"""
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        if not employee:
            return request.redirect(MY_EMPLOYEE_URL)

        domain = [
            ('employee_id', '=', employee.id),
            ('state', 'in', ['done', 'paid'])
        ]

        month = kwargs.get('month')
        year = kwargs.get('year')

        _logger.info("Payslip filters - month: %s, year: %s", month, year)

        if month and year:
            try:
                from datetime import datetime
                from calendar import monthrange
                start_date = datetime(int(year), int(month), 1)
                end_date = datetime(int(year), int(month), monthrange(int(year), int(month))[1], 23, 59, 59)
                domain += [('date_from', '>=', start_date.strftime('%Y-%m-%d')),
                           ('date_to', '<=', end_date.strftime('%Y-%m-%d'))]
                _logger.info("Date filter applied: %s to %s", start_date.strftime('%Y-%m-%d'),
                             end_date.strftime('%Y-%m-%d'))
            except (ValueError, TypeError) as e:
                _logger.warning("Invalid date filter values - month: %s, year: %s, error: %s", month, year, e)

        _logger.info("Final domain: %s", domain)
        payslips = request.env['hr.payslip'].sudo().search(domain, order='date_from desc, date_to desc')
        _logger.info("Found %d confirmed payslips", len(payslips))

        from datetime import datetime
        current_year = datetime.now().year
        years = list(range(current_year - 5, current_year + 2))
        months = [
            {'value': i, 'name': datetime(2000, i, 1).strftime('%B')} for i in range(1, 13)
        ]

        return request.render('employee_self_service_portal.portal_payslip', {
            'payslips': payslips,
            'employee': employee,
            'years': years,
            'months': months,
            'selected_month': month or '',
            'selected_year': year or '',
        })

    @http.route(MY_EMPLOYEE_URL + '/payslips/download/<int:payslip_id>', type='http', auth='user', website=True)
    def portal_payslip_download(self, payslip_id, **kwargs):
        """Download payslip as PDF"""
        try:
            payslip = request.env['hr.payslip'].sudo().browse(payslip_id)
            # FIX: use request.env.uid instead of deprecated request.uid
            employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)

            if not payslip.exists() or not employee or payslip.employee_id.id != employee.id:
                _logger.warning("Unauthorized payslip access attempt by user %s for payslip %s", request.env.uid,
                                payslip_id)
                return request.redirect(MY_EMPLOYEE_URL + '/payslips?error=access_denied')

            if payslip.state not in ['done', 'paid']:
                _logger.warning("Download attempt for unconfirmed payslip %s by user %s", payslip_id, request.env.uid)
                return request.redirect(MY_EMPLOYEE_URL + '/payslips?error=not_confirmed')

            _logger.info("Attempting to download payslip %s for user %s", payslip_id, request.env.uid)

            report_ref = None
            report_names = [
                'hr_payroll.action_report_payslip',
                'hr_payroll.payslip_report',
                'hr_payroll.report_payslip',
                'hr_payroll.report_payslip_details'
            ]

            for report_name in report_names:
                try:
                    report_ref = request.env.ref(report_name, raise_if_not_found=False)
                    if report_ref:
                        _logger.info("Found report reference: %s", report_name)
                        break
                except Exception as ref_error:
                    _logger.debug("Error checking report %s: %s", report_name, str(ref_error))
                    continue

            if not report_ref:
                _logger.info("Standard reports not found, searching for any payslip reports...")
                try:
                    reports = request.env['ir.actions.report'].sudo().search([
                        ('model', '=', 'hr.payslip'),
                        ('report_type', '=', 'qweb-pdf')
                    ])
                    _logger.info("Found %d payslip reports in system", len(reports))
                    for report in reports:
                        report_ref = report
                        break
                except Exception as search_error:
                    _logger.error("Error searching for reports: %s", str(search_error))

            pdf_content = None
            if report_ref:
                try:
                    report_sudo = report_ref.sudo()
                    try:
                        pdf_content, _ = report_sudo._render_qweb_pdf(report_sudo.report_name, payslip.ids)
                        _logger.info("Successfully used _render_qweb_pdf method")
                    except Exception as method_error:
                        _logger.warning("_render_qweb_pdf failed: %s", str(method_error))
                        try:
                            pdf_content, _ = report_sudo.render_qweb_pdf(payslip.ids)
                            _logger.info("Successfully used render_qweb_pdf method")
                        except Exception as method_error2:
                            _logger.warning("render_qweb_pdf method failed: %s", str(method_error2))
                            try:
                                pdf_content, _ = report_sudo._render(report_sudo.report_name, payslip.ids)
                                _logger.info("Successfully used _render method")
                            except Exception as method_error3:
                                _logger.error("All render methods failed: %s", str(method_error3))
                except Exception as render_error:
                    _logger.error("PDF rendering failed: %s", str(render_error))

            if not pdf_content or len(pdf_content) < 100:
                _logger.warning("Using fallback text export for payslip %s", payslip_id)
                simple_content = "PAYSLIP: {}\nEmployee: {}\nPeriod: {} to {}\nStatus: {}\n\nPayslip Details:\n".format(
                    payslip.number or payslip.id,
                    payslip.employee_id.name,
                    payslip.date_from,
                    payslip.date_to,
                    dict(payslip._fields['state'].selection).get(payslip.state, payslip.state)
                )
                if payslip.line_ids:
                    for line in payslip.line_ids:
                        simple_content += "{}: {:.2f}\n".format(line.name, line.total)
                else:
                    simple_content += "No payslip details available\n"

                safe_number = (payslip.number or str(payslip.id)).replace('/', '_').replace('\\', '_')
                safe_date = payslip.date_from.strftime('%Y-%m') if payslip.date_from else 'unknown'
                filename = "Payslip_{}_{}.txt".format(safe_number, safe_date)

                headers = [
                    ('Content-Type', 'text/plain'),
                    ('Content-Length', len(simple_content.encode('utf-8'))),
                    ('Content-Disposition', 'attachment; filename="{}"'.format(filename)),
                    ('Cache-Control', 'no-cache'),
                ]
                return request.make_response(simple_content.encode('utf-8'), headers=headers)

            safe_number = (payslip.number or str(payslip.id)).replace('/', '_').replace('\\', '_')
            safe_date = payslip.date_from.strftime('%Y-%m') if payslip.date_from else 'unknown'
            filename = "Payslip_{}_{}.pdf".format(safe_number, safe_date)

            pdfhttpheaders = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf_content)),
                ('Content-Disposition', 'attachment; filename="{}"'.format(filename)),
                ('Cache-Control', 'no-cache'),
            ]

            _logger.info("Payslip %s downloaded successfully, size: %d bytes", payslip_id, len(pdf_content))
            return request.make_response(pdf_content, headers=pdfhttpheaders)

        except Exception as e:
            _logger.error("Unexpected error in payslip download for payslip %s: %s", payslip_id, str(e))
            import traceback
            _logger.error("Full traceback: %s", traceback.format_exc())
            return request.redirect(MY_EMPLOYEE_URL + '/payslips?error=download_failed')

    @http.route(MY_EMPLOYEE_URL + '/payslips/view/<int:payslip_id>', type='http', auth='user', website=True)
    def portal_payslip_view(self, payslip_id, **kwargs):
        """View payslip details"""
        payslip = request.env['hr.payslip'].sudo().browse(payslip_id)
        # FIX: use request.env.uid instead of deprecated request.uid
        employee = request.env[HR_EMPLOYEE_MODEL].sudo().search([('user_id', '=', request.env.uid)], limit=1)

        if not payslip or not employee or payslip.employee_id.id != employee.id:
            return request.redirect(MY_EMPLOYEE_URL + '/payslips')

        return request.render('employee_self_service_portal.portal_payslip_view', {
            'payslip': payslip,
            'employee': employee,
        })

    @http.route('/my/employee/crm/update_stage/<int:lead_id>', type='http', auth='user', website=True, methods=['POST'],
                csrf=True)
    def portal_employee_crm_update_stage(self, lead_id, **post):
        """Route to handle stage updates via AJAX"""
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user

        if not lead or lead.user_id.id != user.id:
            response = json.dumps({'success': False, 'error': 'Access denied'})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

        stage_id = post.get('stage_id')
        if not stage_id:
            response = json.dumps({'success': False, 'error': 'Stage ID is required'})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

        try:
            stage_id = int(stage_id)
            stage = request.env['crm.stage'].sudo().browse(stage_id)
            if not stage.exists():
                response = json.dumps({'success': False, 'error': 'Invalid stage'})
                return request.make_response(response, headers={'Content-Type': 'application/json'})

            lead.write({'stage_id': stage_id})
            response = json.dumps({'success': True, 'stage_name': stage.name})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

        except Exception as e:
            _logger.error("Error updating lead stage: %s", str(e))
            response = json.dumps({'success': False, 'error': 'Update failed'})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

    @http.route('/my/employee/crm/api/kpis', type='http', auth='user', website=True, methods=['GET'], csrf=False)
    def portal_employee_crm_api_kpis(self, **kwargs):
        """API endpoint to get dashboard KPIs"""
        from datetime import date

        user = request.env.user

        try:
            all_user_leads = request.env['crm.lead'].sudo().search([('user_id', '=', user.id)])
            today = date.today()
            kpis = self._calculate_dashboard_kpis(all_user_leads, today)

            response = json.dumps({'success': True, 'kpis': kpis})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

        except Exception as e:
            _logger.error("Error fetching KPIs: %s", str(e))
            response = json.dumps({'success': False, 'error': 'Failed to fetch KPIs'})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

    @http.route('/my/employee/crm/api/quick_action', type='http', auth='user', website=True, methods=['POST'],
                csrf=True)
    def portal_employee_crm_quick_action(self, **post):
        """API endpoint for quick actions on leads"""
        user = request.env.user
        action = post.get('action')
        lead_id = post.get('lead_id')

        try:
            lead_id = int(lead_id)
            lead = request.env['crm.lead'].sudo().browse(lead_id)

            if not lead or lead.user_id.id != user.id:
                response = json.dumps({'success': False, 'error': 'Access denied'})
                return request.make_response(response, headers={'Content-Type': 'application/json'})

            if action == 'mark_won':
                won_stage = request.env['crm.stage'].sudo().search([('name', '=ilike', 'won')], limit=1)
                if won_stage:
                    lead.write({'stage_id': won_stage.id})
                    response = json.dumps({'success': True, 'message': 'Lead marked as won'})
                else:
                    response = json.dumps({'success': False, 'error': 'Won stage not found'})

            elif action == 'mark_lost':
                lost_stage = request.env['crm.stage'].sudo().search([('name', '=ilike', 'lost')], limit=1)
                if lost_stage:
                    lead.write({'stage_id': lost_stage.id})
                else:
                    lead.write({'active': False})
                response = json.dumps({'success': True, 'message': 'Lead marked as lost'})

            elif action == 'schedule_call':
                activity_type = request.env['mail.activity.type'].sudo().search([('name', '=ilike', 'call')], limit=1)
                if not activity_type:
                    activity_type = request.env['mail.activity.type'].sudo().search([], limit=1)

                if activity_type:
                    from datetime import date, timedelta
                    request.env['mail.activity'].sudo().create({
                        'res_id': lead.id,
                        'res_model_id': request.env['ir.model']._get('crm.lead').id,
                        'activity_type_id': activity_type.id,
                        'summary': 'Scheduled Call',
                        'date_deadline': date.today() + timedelta(days=1),
                        'user_id': user.id,
                    })
                    response = json.dumps({'success': True, 'message': 'Call scheduled for tomorrow'})
                else:
                    response = json.dumps({'success': False, 'error': 'Could not create activity'})

            elif action == 'add_note':
                note_content = post.get('note_content', '')
                if note_content:
                    lead.message_post(body=note_content, message_type='comment')
                    response = json.dumps({'success': True, 'message': 'Note added'})
                else:
                    response = json.dumps({'success': False, 'error': 'Note content required'})

            else:
                response = json.dumps({'success': False, 'error': 'Unknown action'})

            return request.make_response(response, headers={'Content-Type': 'application/json'})

        except Exception as e:
            _logger.error("Error in quick action: %s", str(e))
            response = json.dumps({'success': False, 'error': 'Action failed'})
            return request.make_response(response, headers={'Content-Type': 'application/json'})

    @http.route('/my/employee/crm/notes_modal/<int:lead_id>', type='http', auth='user', website=True)
    def portal_employee_crm_notes_modal(self, lead_id, **kwargs):
        """Route to handle notes modal content loading"""
        lead = request.env['crm.lead'].sudo().browse(lead_id)
        user = request.env.user

        if not lead or lead.user_id.id != user.id:
            return '<div class="alert alert-danger">Access denied</div>'

        notes = request.env['mail.message'].sudo().search([
            ('model', '=', 'crm.lead'),
            ('res_id', '=', lead_id),
            ('message_type', '=', 'comment'),
            ('subtype_id', '=', request.env.ref('mail.mt_note').id)
        ], order='date desc')

        context = {
            'lead': lead,
            'notes': notes,
        }

        return request.render('employee_self_service_portal.portal_employee_crm_notes_modal', context)