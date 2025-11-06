#!/usr/bin/env python3
import os
import json
import hashlib
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional

import jwt
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    jsonify,
    request,
    g,
    redirect,
    url_for,
    make_response,
    session,
)
from flask_cors import CORS
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from models import db, Event, EventParticipant, User, Follow

def create_app() -> Flask:
    app = Flask(__name__)

    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hopon.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
    app.config['GOOGLE_REDIRECT_URI'] = os.environ.get(
        'GOOGLE_REDIRECT_URI',
        'http://localhost:8000/auth/google/callback',
    )
    app.config['JWT_SECRET'] = os.environ.get('JWT_SECRET', 'dev-jwt-secret')
    app.config['JWT_ACCESS_EXPIRES'] = int(os.environ.get('JWT_ACCESS_EXPIRES', '900'))  # 15 minutes
    app.config['JWT_REFRESH_EXPIRES'] = int(os.environ.get('JWT_REFRESH_EXPIRES', '604800'))  # 7 days
    app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

    # Initialize extensions
    db.init_app(app)
    frontend_origin = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')
    CORS(app, supports_credentials=True, resources={r"/*": {"origins": [frontend_origin]}})

    oauth = OAuth()
    oauth.init_app(app)
    if app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET']:
        oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile',
                'prompt': 'select_account',
                'access_type': 'offline',
            },
        )
    
    # Create tables
    def generate_token(user_id: int, token_type: str, expires_in: Optional[int] = None) -> str:
        if expires_in is None:
            expires_in = (
                app.config['JWT_REFRESH_EXPIRES']
                if token_type == 'refresh'
                else app.config['JWT_ACCESS_EXPIRES']
            )
        now = datetime.utcnow()
        payload = {
            'sub': user_id,
            'type': token_type,
            'iat': now,
            'exp': now + timedelta(seconds=expires_in),
        }
        return jwt.encode(payload, app.config['JWT_SECRET'], algorithm='HS256')

    def decode_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
        try:
            payload = jwt.decode(token, app.config['JWT_SECRET'], algorithms=['HS256'])
        except jwt.PyJWTError:
            return None
        if expected_type and payload.get('type') != expected_type:
            return None
        return payload

    def ensure_unique_username(base: str) -> str:
        candidate = base
        suffix = 1
        while User.query.filter_by(username=candidate).first():
            candidate = f"{base}{suffix}"
            suffix += 1
        return candidate

    def ensure_host_participant(event: Event) -> None:
        """Ensure the event host is registered as a participant."""
        if not event.host_user_id:
            return
        host = User.query.get(event.host_user_id)
        if not host:
            return
        existing = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=event.host_user_id,
        ).first()
        if existing:
            return
        db.session.add(
            EventParticipant(
                event_id=event.id,
                user_id=event.host_user_id,
                player_name=host.username,
                team="host",
            )
        )

    def get_google_client():
        client = oauth.create_client('google')
        if client is None:
            raise RuntimeError("Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
        return client

    def seed_initial_data() -> None:
        """Populate the database with baseline data for local development."""
        seed_users = [
            dict(
                username="Alex Chen",
                email="alex@example.com",
                bio="Basketball enthusiast, love pickup games and meeting new people!",
                gender="male",
                rating=4.8,
                location="Downtown",
                sports="Basketball,Tennis",
            ),
            dict(
                username="Sarah Miller",
                email="sarah@example.com",
                bio="Tennis coach by day, competitive player by night.",
                gender="female",
                rating=4.9,
                location="Riverside",
                sports="Tennis,Badminton",
            ),
            dict(
                username="Emily Carter",
                email="emily@example.com",
                bio="Early morning runner seeking new trails and partners for weekend 5Ks.",
                gender="female",
                rating=4.4,
                location="Harborfront",
                sports="Running,Yoga",
            ),
        ]

        created_user = False
        for payload in seed_users:
            if not User.query.filter_by(username=payload["username"]).first():
                db.session.add(User(**payload))
                created_user = True
        if created_user:
            db.session.commit()

        host = User.query.filter_by(username="Alex Chen").first()
        if host:
            now = datetime.utcnow()
            seed_events = [
                dict(
                    name="Downtown Pickup Game",
                    sport="Basketball",
                    location="Central Park Courts",
                    notes="Intermediate run with friendly competition.",
                    max_players=10,
                    event_date=now + timedelta(hours=2),
                    latitude=43.6532,
                    longitude=-79.3832,
                    skill_level="Intermediate",
                ),
                dict(
                    name="Sunrise Run Crew",
                    sport="Running",
                    location="Harborfront Boardwalk",
                    notes="Casual 5K with coffee afterwards.",
                    max_players=25,
                    event_date=now + timedelta(hours=6),
                    latitude=43.6408,
                    longitude=-79.3818,
                    skill_level="All Levels",
                ),
                dict(
                    name="Twilight Tennis Doubles",
                    sport="Tennis",
                    location="Riverside Tennis Club",
                    notes="Advanced doubles ladder. Bring your own racket.",
                    max_players=4,
                    event_date=now + timedelta(days=1),
                    latitude=43.7001,
                    longitude=-79.3568,
                    skill_level="Advanced",
                ),
            ]

            created_event = False
            for payload in seed_events:
                if not Event.query.filter_by(name=payload["name"]).first():
                    db.session.add(Event(host_user_id=host.id, **payload))
                    created_event = True
            if created_event:
                db.session.commit()
                host_events = Event.query.filter_by(host_user_id=host.id).all()
                created_participant = False
                for event in host_events:
                    existing_count = EventParticipant.query.filter_by(
                        event_id=event.id,
                        user_id=event.host_user_id,
                    ).count()
                    if existing_count == 0:
                        ensure_host_participant(event)
                        created_participant = True
                if created_participant:
                    db.session.commit()

    with app.app_context():
        db.create_all()
        seed_initial_data()

    @app.before_request
    def attach_current_user():
        g.current_user = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1].strip()
            payload = decode_token(token, expected_type='access')
            if payload:
                user = User.query.get(payload.get('sub'))
                if user:
                    g.current_user = user

    @app.get("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.get("/hello")
    def hello():
        name = request.args.get("name", "world")
        return jsonify(message=f"Hello, {name}!") , 200

    @app.get("/auth/google/login")
    def google_login():
        try:
            client = get_google_client()
        except RuntimeError as exc:
            return jsonify({'error': str(exc)}), 500
        redirect_uri = url_for("google_callback", _external=True)
        next_url = request.args.get('next') or frontend_origin
        session['oauth_next'] = next_url
        return client.authorize_redirect(redirect_uri)

    @app.get("/auth/google/callback")
    def google_callback():
        try:
            client = get_google_client()
            token = client.authorize_access_token()
        except Exception as exc:  # noqa: W0703 - surface error to client
            return jsonify({'error': f'Failed to authorize with Google: {exc}'}), 400

        userinfo = token.get('userinfo')
        if not userinfo:
            try:
                userinfo = client.parse_id_token(token)
            except Exception as exc:  # noqa: W0703
                return jsonify({'error': f'Failed to fetch Google user info: {exc}'}), 400

        google_sub = userinfo.get('sub')
        email = userinfo.get('email')
        if not google_sub or not email:
            return jsonify({'error': 'Google profile is missing required information (sub, email).'}), 400

        user = User.query.filter(or_(User.google_sub == google_sub, User.email == email)).first()
        display_name = userinfo.get('name') or email.split('@')[0]
        given_name = userinfo.get('given_name') or display_name
        username_seed = "".join(ch if ch.isalnum() else "_" for ch in given_name.lower()).strip("_") or "player"

        if not user:
            username = ensure_unique_username(username_seed)
            user = User(
                username=username,
                email=email,
                bio=userinfo.get('profile'),
                gender=None,
                rating=None,
                location=None,
                sports=None,
                google_sub=google_sub,
                avatar_url=userinfo.get('picture'),
            )
            db.session.add(user)
        else:
            user.google_sub = user.google_sub or google_sub
            if userinfo.get('picture'):
                user.avatar_url = userinfo.get('picture')

        db.session.commit()

        access_token = generate_token(user.id, 'access')
        refresh_token = generate_token(user.id, 'refresh')

        payload = {
            'message': 'Login successful',
            'user': user.to_dict(),
            'access_token': access_token,
        }
        redirect_target = session.pop('oauth_next', frontend_origin)
        if not isinstance(redirect_target, str) or not redirect_target.startswith(frontend_origin):
            redirect_target = frontend_origin
        script = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Signing in…</title>
  </head>
  <body>
    <script>
      (function() {{
        const payload = {json.dumps(payload)};
        if (window.opener && window.opener !== window) {{
          window.opener.postMessage({{ type: "hopon:auth", payload }}, "{frontend_origin}");
          window.close();
        }} else {{
          window.localStorage.setItem("hoponAuthPayload", JSON.stringify(payload));
          window.location.replace("{redirect_target}");
        }}
      }})();
    </script>
    <p>Signing you in…</p>
  </body>
</html>"""

        response = make_response(script)
        response.headers['Content-Type'] = 'text/html'
        response.set_cookie(
            'refresh_token',
            refresh_token,
            max_age=app.config['JWT_REFRESH_EXPIRES'],
            httponly=True,
            secure=app.config['SESSION_COOKIE_SECURE'],
            samesite=app.config['SESSION_COOKIE_SAMESITE'],
        )
        return response

    @app.post("/auth/refresh")
    def refresh_access_token():
        refresh_token = request.cookies.get('refresh_token')
        if not refresh_token:
            return jsonify({'error': 'Missing refresh token'}), 401
        payload = decode_token(refresh_token, expected_type='refresh')
        if not payload:
            response = make_response(jsonify({'error': 'Invalid refresh token'}), 401)
            response.delete_cookie('refresh_token')
            return response
        user = User.query.get(payload.get('sub'))
        if not user:
            response = make_response(jsonify({'error': 'Unknown user'}), 401)
            response.delete_cookie('refresh_token')
            return response
        access_token = generate_token(user.id, 'access')
        return jsonify({'access_token': access_token, 'user': user.to_dict()})

    @app.post("/auth/logout")
    def logout():
        response = make_response(jsonify({'message': 'Logged out'}))
        response.delete_cookie('refresh_token')
        return response

    @app.get("/auth/session")
    def session_info():
        if g.current_user:
            return jsonify({'authenticated': True, 'user': g.current_user.to_dict()}), 200
        refresh_token = request.cookies.get('refresh_token')
        if refresh_token:
            payload = decode_token(refresh_token, expected_type='refresh')
            if payload:
                user = User.query.get(payload.get('sub'))
                if user:
                    access_token = generate_token(user.id, 'access')
                    return (
                        jsonify(
                            {
                                'authenticated': True,
                                'user': user.to_dict(),
                                'access_token': access_token,
                            }
                        ),
                        200,
                    )
        return jsonify({'authenticated': False}), 401

    # Event Management
    # Utility
    def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Compute haversine distance in km between two coordinates."""
        from math import radians, sin, cos, asin, sqrt
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        R = 6371.0
        return R * c

    @app.post("/events")
    def create_event():
        """Create a new event"""
        data = request.get_json() or {}

        if not all(k in data for k in ['name', 'sport', 'location', 'max_players']):
            return jsonify({'error': 'Missing required fields: name, sport, location, max_players'}), 400
        
        try:
            host_user_id = g.current_user.id if g.current_user else data.get('host_user_id')
            event = Event(
                name=data['name'],
                sport=data['sport'],
                location=data['location'],
                notes=data.get('notes'),
                max_players=data['max_players'],
                event_date=datetime.fromisoformat(data['event_date']) if data.get('event_date') else None,
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                skill_level=data.get('skill_level'),
                host_user_id=host_user_id,
            )
            
            db.session.add(event)
            db.session.flush()
            if host_user_id:
                ensure_host_participant(event)
            db.session.commit()
            
            return jsonify({
                'message': 'Event created successfully',
                'event': event.to_dict()
            }), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': 'Failed to create event'}), 500

    @app.get("/events")
    def get_events():
        """Get all available events/games"""
        events = Event.query.order_by(Event.created_at.desc()).all()
        return jsonify([event.to_dict() for event in events]), 200

    @app.get("/events/nearby")
    def nearby_events():
        """Return events with optional haversine distance sorting."""
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        events = Event.query.all()
        out = []
        for e in events:
            d = None
            if lat is not None and lng is not None and e.latitude is not None and e.longitude is not None:
                d = haversine_km(lat, lng, e.latitude, e.longitude)
            item = e.to_dict()
            item['distance_km'] = d
            out.append(item)
        # Sort by distance if present
        out.sort(key=lambda x: x['distance_km'] if x['distance_km'] is not None else 1e9)
        return jsonify(out), 200

    @app.get("/events/<int:event_id>")
    def get_event(event_id):
        """Get a specific event by ID"""
        event = Event.query.get_or_404(event_id)
        return jsonify(event.to_dict()), 200

    @app.post("/events/<int:event_id>/join")
    def join_event(event_id):
        """Join a specific event/game"""
        data = request.get_json() or {}
        event = Event.query.get_or_404(event_id)

        user = g.current_user
        team = data.get('team', 'team_a')
        guest_token = data.get('guest_token')
        hashed_guest_token: Optional[str] = None

        if user:
            player_name = data.get('player_name') or user.username
            existing = EventParticipant.query.filter_by(event_id=event_id, user_id=user.id).first()
            if existing:
                return jsonify({'message': 'Already joined', 'event': event.to_dict()}), 200
            user_id = user.id
            guest_name = None
        else:
            player_name = data.get('player_name')
            if not player_name:
                return jsonify({'error': 'Player name is required'}), 400
            guest_name = player_name
            if guest_token:
                hashed_guest_token = hashlib.sha256(guest_token.encode()).hexdigest()
                existing = EventParticipant.query.filter_by(
                    event_id=event_id,
                    guest_token=hashed_guest_token,
                ).first()
                if existing:
                    return jsonify({'message': 'Already joined', 'event': event.to_dict()}), 200
            else:
                guest_token = uuid4().hex
                hashed_guest_token = hashlib.sha256(guest_token.encode()).hexdigest()
            user_id = None

        if event.participants.count() >= event.max_players:
            return jsonify({'error': 'Event is full'}), 409
        
        try:
            participant = EventParticipant(
                event_id=event_id,
                user_id=user_id,
                player_name=player_name,
                team=team,
                guest_name=guest_name,
                guest_token=hashed_guest_token,
            )
            
            db.session.add(participant)
            db.session.commit()

            response_payload = {
                'message': 'Successfully joined event',
                'event': event.to_dict()
            }
            if not user and guest_token:
                response_payload['guest_token'] = guest_token
            return jsonify(response_payload), 200
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Failed to join event'}), 409
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': 'Failed to join event'}), 500

    @app.post("/events/<int:event_id>/leave")
    def leave_event(event_id: int):
        data = request.get_json() or {}
        user = g.current_user
        if user:
            participant = EventParticipant.query.filter_by(event_id=event_id, user_id=user.id).first()
        else:
            guest_token = data.get('guest_token')
            if not guest_token:
                return jsonify({'error': 'guest_token is required for guest users'}), 400
            hashed_guest_token = hashlib.sha256(guest_token.encode()).hexdigest()
            participant = EventParticipant.query.filter_by(
                event_id=event_id,
                guest_token=hashed_guest_token,
            ).first()
        if not participant:
            return jsonify({'message': 'Not a participant'}), 200
        db.session.delete(participant)
        db.session.commit()
        return jsonify({'message': 'Left event'}), 200

    @app.get("/events/<int:event_id>/participants")
    def get_event_participants(event_id):
        """Get all participants for a specific event"""
        event = Event.query.get_or_404(event_id)
        participants = EventParticipant.query.filter_by(event_id=event_id).all()
        
        return jsonify({
            'event': event.to_dict(),
            'participants': [participant.to_dict() for participant in participants]
        }), 200

    # User Management
    @app.post("/users")
    def create_user():
        data = request.get_json()
        if not data or not all(k in data for k in ["username", "email"]):
            return jsonify({"error": "Missing required fields: username, email"}), 400
        try:
            user = User(
                username=data["username"],
                email=data["email"],
                bio=data.get("bio"),
                gender=data.get("gender")
            )
            db.session.add(user)
            db.session.commit()
            return jsonify({"message": "User created successfully", "user": user.to_dict()}), 201
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "Username or email already exists"}), 409
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": "Failed to create user"}), 500

    @app.get("/users/<int:user_id>")
    def get_user(user_id):
        user = User.query.get_or_404(user_id)
        return jsonify(user.to_dict()), 200

    @app.get("/users/nearby")
    def users_nearby():
        """Simple nearby users endpoint. For now returns all users with discovery fields."""
        users = User.query.all()
        following_lookup = set()
        if g.current_user:
            following_lookup = {
                f.followee_id for f in Follow.query.filter_by(follower_id=g.current_user.id).all()
            }
        out = []
        for u in users:
            payload = u.to_dict()
            payload['events_count'] = EventParticipant.query.filter_by(user_id=u.id).count()
            # compatibility camelCase
            payload['eventsCount'] = payload['events_count']
            payload['is_following'] = u.id in following_lookup if g.current_user else False
            out.append(payload)
        return jsonify(out), 200

    @app.post("/users/<int:user_id>/follow")
    def follow_user(user_id: int):
        data = request.get_json() or {}
        follower_id = g.current_user.id if g.current_user else data.get('follower_id')
        if follower_id is None:
            return jsonify({'error': 'follower_id is required'}), 400
        if follower_id == user_id:
            return jsonify({'error': 'cannot follow self'}), 400
        exists = Follow.query.filter_by(follower_id=follower_id, followee_id=user_id).first()
        if exists:
            return jsonify({'message': 'Already following'}), 200
        db.session.add(Follow(follower_id=follower_id, followee_id=user_id))
        db.session.commit()
        return jsonify({'message': 'Followed'}), 200

    @app.delete("/users/<int:user_id>/follow")
    def unfollow_user(user_id: int):
        follower_id = g.current_user.id if g.current_user else request.args.get('follower_id', type=int)
        if follower_id is None:
            data = request.get_json(silent=True) or {}
            follower_id = data.get('follower_id')
        if follower_id is None:
            return jsonify({'error': 'follower_id is required'}), 400
        f = Follow.query.filter_by(follower_id=follower_id, followee_id=user_id).first()
        if not f:
            return jsonify({'message': 'Not following'}), 200
        db.session.delete(f)
        db.session.commit()
        return jsonify({'message': 'Unfollowed'}), 200

    @app.get("/me/events")
    def my_events():
        """Return joined and hosted events for a user."""
        user_id = g.current_user.id if g.current_user else request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400
        joined_ep = EventParticipant.query.filter_by(user_id=user_id).all()
        joined_ids = {ep.event_id for ep in joined_ep}
        joined = [Event.query.get(eid).to_dict() for eid in joined_ids if Event.query.get(eid)]
        hosted = Event.query.filter_by(host_user_id=user_id).all()
        return jsonify({
            'joined': joined,
            'hosted': [e.to_dict() for e in hosted],
        }), 200

    return app
    

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
