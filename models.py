from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from typing import Optional

db = SQLAlchemy()

class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sport = db.Column(db.String(50), nullable=False)
    location = db.Column(db.Text, nullable=False)  # venue/address
    notes = db.Column(db.Text, nullable=True)
    max_players = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    event_date = db.Column(db.DateTime, nullable=True)
    # Optional geo + metadata for sorting/filtering
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    skill_level = db.Column(db.String(32), nullable=True)
    host_user_id = db.Column(db.Integer, db.ForeignKey('user_model.id'), nullable=True)
    
    # Relationships
    participants = db.relationship('EventParticipant', backref='event', lazy='dynamic', cascade='all, delete-orphan')
    host = db.relationship('User', backref='events_hosted', foreign_keys=[host_user_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sport': self.sport,
            'location': self.location,
            'notes': self.notes,
            'max_players': self.max_players,
            'current_players': self.participants.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'event_date': self.event_date.isoformat() if self.event_date else None,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'skill_level': self.skill_level,
            'host_user_id': self.host_user_id,
            'host': self.host.to_public_dict() if self.host else None,
        }

class EventParticipant(db.Model):
    __tablename__ = 'event_participants'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user_model.id'), nullable=True)
    player_name = db.Column(db.String(100), nullable=False)
    team = db.Column(db.String(20), nullable=True)  # 'team_a' or 'team_b'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'user_id': self.user_id,
            'player_name': self.player_name,
            'team': self.team,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None
        }

class User(db.Model):
    __tablename__ = 'user_model'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    bio = db.Column(db.Text, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Simple discovery fields
    rating = db.Column(db.Float, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    sports = db.Column(db.Text, nullable=True)  # comma-separated list

    # Relationship to events through EventParticipant
    events_joined = db.relationship('EventParticipant', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_public_dict(self):
        return {
            'id': self.id,
            'username': self.username,
        }
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'bio': self.bio,
            'gender': self.gender,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'rating': self.rating,
            'location': self.location,
            'sports': [s.strip() for s in self.sports.split(',')] if self.sports else None,
        }

class Follow(db.Model):
    __tablename__ = 'follows'
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user_model.id'), nullable=False)
    followee_id = db.Column(db.Integer, db.ForeignKey('user_model.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
