#!/usr/bin/env python3
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from models import db, Event, EventParticipant, User, Follow
from datetime import datetime
from sqlalchemy.exc import IntegrityError

def create_app() -> Flask:
    app = Flask(__name__)
    
    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hopon.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    
    # Initialize extensions
    db.init_app(app)
    CORS(app)
    
    # Create tables
    with app.app_context():
        db.create_all()

    @app.get("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.get("/hello")
    def hello():
        name = request.args.get("name", "world")
        return jsonify(message=f"Hello, {name}!") , 200

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
        data = request.get_json()
        
        if not data or not all(k in data for k in ['name', 'sport', 'location', 'max_players']):
            return jsonify({'error': 'Missing required fields: name, sport, location, max_players'}), 400
        
        try:
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
                host_user_id=data.get('host_user_id'),
            )
            
            db.session.add(event)
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
        data = request.get_json()
        
        if not data or not data.get('player_name'):
            return jsonify({'error': 'Player name is required'}), 400
        
        event = Event.query.get_or_404(event_id)
        player_name = data['player_name']
        team = data.get('team', 'team_a')  # Default to team_a
        user_id = data.get('user_id')
        
        # Check if event is full
        if event.participants.count() >= event.max_players:
            return jsonify({'error': 'Event is full'}), 409
        
        try:
            # Prevent duplicate join by same user
            if user_id is not None:
                existing = EventParticipant.query.filter_by(event_id=event_id, user_id=user_id).first()
                if existing:
                    return jsonify({'message': 'Already joined', 'event': event.to_dict()}), 200
            participant = EventParticipant(event_id=event_id, user_id=user_id, player_name=player_name, team=team)
            
            db.session.add(participant)
            db.session.commit()
            
            return jsonify({
                'message': 'Successfully joined event',
                'event': event.to_dict()
            }), 200
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Failed to join event'}), 409
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': 'Failed to join event'}), 500

    @app.post("/events/<int:event_id>/leave")
    def leave_event(event_id: int):
        data = request.get_json() or {}
        user_id = data.get('user_id')
        if user_id is None:
            return jsonify({'error': 'user_id is required'}), 400
        participant = EventParticipant.query.filter_by(event_id=event_id, user_id=user_id).first()
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
        out = []
        for u in users:
            payload = u.to_dict()
            payload['events_count'] = EventParticipant.query.filter_by(user_id=u.id).count()
            out.append(payload)
        return jsonify(out), 200

    @app.post("/users/<int:user_id>/follow")
    def follow_user(user_id: int):
        data = request.get_json() or {}
        follower_id = data.get('follower_id')
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
        follower_id = request.args.get('follower_id', type=int)
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
        user_id = request.args.get('user_id', type=int)
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
