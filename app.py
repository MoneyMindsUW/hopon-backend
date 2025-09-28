#!/usr/bin/env python3
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from models import db, Event, EventParticipant
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
                event_date=datetime.fromisoformat(data['event_date']) if data.get('event_date') else None
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
        
        # Check if event is full
        if event.participants.count() >= event.max_players:
            return jsonify({'error': 'Event is full'}), 409
        
        try:
            participant = EventParticipant(
                event_id=event_id,
                player_name=player_name,
                team=team
            )
            
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

    @app.get("/events/<int:event_id>/participants")
    def get_event_participants(event_id):
        """Get all participants for a specific event"""
        event = Event.query.get_or_404(event_id)
        participants = EventParticipant.query.filter_by(event_id=event_id).all()
        
        return jsonify({
            'event': event.to_dict(),
            'participants': [participant.to_dict() for participant in participants]
        }), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
