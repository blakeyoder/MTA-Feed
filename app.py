# coding: utf-8
"""
    mta-api-sanity
    ~~~~~~

    Expose the MTA's real-time subway feed as a json api

    :copyright: (c) 2014 by Jon Thornton.
    :license: BSD, see LICENSE for more details.
"""

from mtapi import Mtapi
from flask import Flask, request, jsonify, abort, render_template
from flask.json import JSONEncoder
from datetime import datetime
from functools import wraps
import jinja2
import arrow
import logging
import os

app = Flask(__name__)
app.config.update(
    MAX_TRAINS=10,
    MAX_MINUTES=30,
    CACHE_SECONDS=60,
    THREADED=True
)

def timeago(dt):
    dt = arrow.get(dt)
    return dt.humanize()

app.jinja_env.filters['timeago'] = timeago

_SETTINGS_ENV_VAR = 'MTAPI_SETTINGS'
_SETTINGS_DEFAULT_PATH = './settings.cfg'
if _SETTINGS_ENV_VAR in os.environ:
    app.config.from_envvar(_SETTINGS_ENV_VAR)
elif os.path.isfile(_SETTINGS_DEFAULT_PATH):
    app.config.from_pyfile(_SETTINGS_DEFAULT_PATH)
else:
    raise Exception('No configuration found! Create a settings.cfg file or set MTAPI_SETTINGS env variable.')

app.debug = True
# set debug logging
if app.debug:
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

class CustomJSONEncoder(JSONEncoder):

    def default(self, obj):
        try:
            if isinstance(obj, datetime):
                return obj.isoformat()
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)


app.json_encoder = CustomJSONEncoder

mta = Mtapi(
    os.environ.get('MTA_KEY'),
    app.config['STATIONS_FILE'],
    max_trains=app.config['MAX_TRAINS'],
    max_minutes=app.config['MAX_MINUTES'],
    expires_seconds=app.config['CACHE_SECONDS'],
    threaded=app.config['THREADED'])

def cross_origin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        resp = f(*args, **kwargs)

        if app.config['DEBUG']:
            resp.headers['Access-Control-Allow-Origin'] = '*'
        elif 'CROSS_ORIGIN' in app.config:
            resp.headers['Access-Control-Allow-Origin'] = app.config['CROSS_ORIGIN']

        return resp

    return decorated_function


@app.route('/')
def index():
    data = {
        'data': sorted(mta.get_routes()),
        'updated': mta.last_update()
    }
    return render_template('index.html', data=data)


@app.route('/<route>')
def route(route):
    data = _by_route(route)
    if not data['data']:
        return render_template('404.html', data=route), 404
    return render_template('route.html', data=data['data'])


@app.route('/by-location', methods=['GET'])
@cross_origin
def by_location():
    try:
        location = (float(request.args['lat']), float(request.args['lon']))
    except KeyError as e:
        print e
        response = jsonify({
            'error': 'Missing lat/lon parameter'
        })
        response.status_code = 400
        return response

    data = mta.get_by_point(location, 5)
    return _make_envelope(data)


@app.route('/by-route/<route>', methods=['GET'])
def by_route(route):
    return jsonify(_by_route(route))


def _by_route(route):
    try:
        if route.isalpha():
            route = route.upper()
        data = mta.get_by_route(route)
        return _make_envelope(data)
    except KeyError:
        abort(404)


@app.route('/by-id/<id_string>', methods=['GET'])
@cross_origin
def by_index(id_string):
    ids = id_string.split(',')
    try:
        data = mta.get_by_id(ids)
        return _make_envelope(data)
    except KeyError:
        abort(404)


@app.route('/routes', methods=['GET'])
@cross_origin
def routes():
    return jsonify({
        'data': sorted(mta.get_routes()),
        'updated': mta.last_update()
    })

def _envelope_reduce(a, b):
    if a['last_update'] and b['last_update']:
        return a if a['last_update'] < b['last_update'] else b
    elif a['last_update']:
        return a
    else:
        return b


def _make_envelope(data):
    time = None
    if data:
        time = reduce(_envelope_reduce, data)['last_update']

    return {
        'data': data,
        'updated': time
    }


if __name__ == '__main__':
    app.run(use_reloader=False)
