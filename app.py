import json
import os
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

DATA_FILE = os.path.join('data', 'bookings.json')
EXTERNAL_ICS = os.path.join('data', 'external_bookings.ics')


def load_bookings():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return []


def save_bookings(bookings):
    with open(DATA_FILE, 'w') as f:
        json.dump(bookings, f)


def parse_ics(path):
    bookings = []
    if not os.path.exists(path):
        return bookings
    start = end = name = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line == 'BEGIN:VEVENT':
                start = end = name = None
            elif line.startswith('SUMMARY:'):
                name = line[len('SUMMARY:'):]
            elif line.startswith('DTSTART'):
                date = line.split(':', 1)[1]
                start = datetime.strptime(date, '%Y%m%d').date()
            elif line.startswith('DTEND'):
                date = line.split(':', 1)[1]
                end = datetime.strptime(date, '%Y%m%d').date() - timedelta(days=1)
            elif line == 'END:VEVENT' and start and end:
                bookings.append({'name': name or 'external',
                                 'start': start.isoformat(),
                                 'end': end.isoformat()})
    return bookings


def conflict(new_start, new_end, bookings):
    ns = datetime.strptime(new_start, '%Y-%m-%d').date()
    ne = datetime.strptime(new_end, '%Y-%m-%d').date()
    for b in bookings:
        bs = datetime.strptime(b['start'], '%Y-%m-%d').date()
        be = datetime.strptime(b['end'], '%Y-%m-%d').date()
        if ns <= be and ne >= bs:
            return True
    return False


def render(template_name, **context):
    path = os.path.join('templates', template_name)
    with open(path) as f:
        html = f.read()
    for k, v in context.items():
        html = html.replace('{{ ' + k + ' }}', str(v))
    return html.encode('utf-8')


def bookings_table(bookings):
    rows = ['<table><tr><th>Name</th><th>Start</th><th>End</th></tr>']
    for b in bookings:
        rows.append(f"<tr><td>{b['name']}</td><td>{b['start']}</td><td>{b['end']}</td></tr>")
    rows.append('</table>')
    return ''.join(rows)


def generate_ics(bookings):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Chapel Stay//EN']
    for i, b in enumerate(bookings):
        start = datetime.strptime(b['start'], '%Y-%m-%d').strftime('%Y%m%d')
        end = (datetime.strptime(b['end'], '%Y-%m-%d') + timedelta(days=1)).strftime('%Y%m%d')
        lines.extend([
            'BEGIN:VEVENT',
            f'UID:{i}@chapel',
            f'SUMMARY:Booking for {b["name"]}',
            f'DTSTART;VALUE=DATE:{start}',
            f'DTEND;VALUE=DATE:{end}',
            'END:VEVENT'
        ])
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines).encode('utf-8')


def app(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')

    if path.startswith('/static/'):
        file_path = path.lstrip('/')
        if os.path.exists(file_path):
            start_response('200 OK', [('Content-Type', 'application/octet-stream')])
            with open(file_path, 'rb') as f:
                return [f.read()]
        start_response('404 Not Found', [])
        return [b'Not Found']

    if path == '/':
        start_response('200 OK', [('Content-Type', 'text/html')])
        return [render('index.html')]

    if path == '/tours':
        start_response('200 OK', [('Content-Type', 'text/html')])
        return [render('tours.html')]

    bookings = load_bookings() + parse_ics(EXTERNAL_ICS)

    if path == '/booking':
        if method == 'POST':
            try:
                size = int(environ.get('CONTENT_LENGTH', 0))
            except ValueError:
                size = 0
            body = environ['wsgi.input'].read(size).decode()
            data = parse_qs(body)
            name = data.get('name', [''])[0]
            start_date = data.get('start', [''])[0]
            end_date = data.get('end', [''])[0]
            if not (name and start_date and end_date):
                start_response('400 Bad Request', [('Content-Type', 'text/plain')])
                return [b'Missing fields']
            if conflict(start_date, end_date, bookings):
                start_response('409 Conflict', [('Content-Type', 'text/plain')])
                return [b'Dates not available']
            new_booking = {'name': name, 'start': start_date, 'end': end_date}
            saved = load_bookings()
            saved.append(new_booking)
            save_bookings(saved)
            start_response('303 See Other', [('Location', '/booking')])
            return [b'']
        else:
            table = bookings_table(bookings)
            start_response('200 OK', [('Content-Type', 'text/html')])
            return [render('booking.html', bookings_table=table)]

    if path == '/bookings.ics':
        start_response('200 OK', [('Content-Type', 'text/calendar')])
        return [generate_ics(bookings)]

    start_response('404 Not Found', [('Content-Type', 'text/plain')])
    return [b'Not Found']


if __name__ == '__main__':
    with make_server('', 8000, app) as httpd:
        print('Serving on http://localhost:8000')
        httpd.serve_forever()
