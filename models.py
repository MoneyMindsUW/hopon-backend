from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sport = db.Column(db.String(50), nullable=False)
    location = db.Column(db.Text, nullable=False)  # Google Maps deeplink
    notes = db.Column(db.Text, nullable=True)
    max_players = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    event_date = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    participants = db.relationship('EventParticipant', backref='event', lazy='dynamic', cascade='all, delete-orphan')
    
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
            'event_date': self.event_date.isoformat() if self.event_date else None
        }

class EventParticipant(db.Model):
    __tablename__ = 'event_participants'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    player_name = db.Column(db.String(100), nullable=False)
    team = db.Column(db.String(20), nullable=True)  # 'team_a' or 'team_b'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'player_name': self.player_name,
            'team': self.team,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None
        }