from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Float, DateTime, 
                      Text, ForeignKey, Enum, UniqueConstraint, Boolean)
from sqlalchemy.orm import relationship

class NewsArticle(db.Model):
   __tablename__ = 'news_articles'

   id = db.Column(db.Integer, primary_key=True)
   external_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
   title = db.Column(db.String(255), nullable=False)
   content = db.Column(db.Text)
   url = db.Column(db.String(512))
   published_at = db.Column(db.DateTime)
   source = db.Column(db.String(100))
   sentiment_label = db.Column(db.String(20))
   sentiment_score = db.Column(db.Float)
   sentiment_explanation = db.Column(db.Text)
   brief_summary = db.Column(db.Text)
   key_points = db.Column(db.Text)
   market_impact_summary = db.Column(db.Text)
   ai_summary = db.Column(db.Text)
   ai_insights = db.Column(db.Text)
   ai_sentiment_rating = db.Column(db.Integer)
   created_at = db.Column(db.DateTime, default=datetime.utcnow)
   
   symbols = relationship('ArticleSymbol', back_populates='article', cascade='all, delete-orphan')
   metrics = relationship('ArticleMetric', back_populates='article', cascade='all, delete-orphan')

   def to_dict(self):
       return {
           'id': self.id,
           'external_id': self.external_id,
           'title': self.title,
           'content': self.content,
           'url': self.url,
           'published_at': self.published_at.isoformat() if self.published_at else None,
           'source': self.source,
           'sentiment': {
               'label': self.sentiment_label,
               'score': self.sentiment_score,
               'explanation': self.sentiment_explanation
           },
           'summary': {
               'brief': self.brief_summary,
               'key_points': self.key_points,
               'market_impact': self.market_impact_summary,
               'ai_summary': self.ai_summary,
               'ai_insights': self.ai_insights,
               'ai_sentiment_rating': self.ai_sentiment_rating
           },
           'symbols': [symbol.to_dict() for symbol in self.symbols],
           'metrics': [metric.to_dict() for metric in self.metrics]
       }

class ArticleSymbol(db.Model):
   __tablename__ = 'article_symbols'
   
   article_id = db.Column(db.Integer, db.ForeignKey('news_articles.id', ondelete='CASCADE'), primary_key=True)
   symbol = db.Column(db.String(20), primary_key=True)

   article = db.relationship('NewsArticle', back_populates='symbols')

   __table_args__ = (
       db.UniqueConstraint('article_id', 'symbol'),
   )

   def to_dict(self):
       return {
           'symbol': self.symbol
       }

class ArticleMetric(db.Model):
   __tablename__ = 'article_metrics'

   article_id = db.Column(db.Integer, db.ForeignKey('news_articles.id', ondelete='CASCADE'), primary_key=True)
   metric_type = db.Column(db.Enum('percentage', 'currency', name='metric_type_enum'), primary_key=True)
   metric_value = db.Column(db.Float)
   metric_context = db.Column(db.Text)

   article = db.relationship('NewsArticle', back_populates='metrics')

   def to_dict(self):
       return {
           'type': self.metric_type,
           'value': self.metric_value,
           'context': self.metric_context
       }

class User(UserMixin, db.Model):
   __tablename__ = 'users'
   
   id = db.Column(db.Integer, primary_key=True)
   email = db.Column(db.String(120), unique=True, nullable=False)
   username = db.Column(db.String(64), unique=True, nullable=False)
   password_hash = db.Column(db.String(255), nullable=False)
   first_name = db.Column(db.String(64))
   last_name = db.Column(db.String(64))
   created_at = db.Column(db.DateTime, default=datetime.utcnow)
   last_login = db.Column(db.DateTime)
   is_active = db.Column(db.Boolean, default=True)
   is_admin = db.Column(db.Boolean, default=False)
   role = db.Column(db.String(20), default='user')
   is_google_user = db.Column(db.Boolean, default=False)
   
   def set_password(self, password):
       self.password_hash = generate_password_hash(password)
       
   def check_password(self, password):
       return check_password_hash(self.password_hash, password)
   
   def update_last_login(self):
       self.last_login = datetime.utcnow()
       db.session.commit()
       
   @property
   def is_administrator(self):
       return self.is_admin or self.role == 'admin'
       
   def to_dict(self):
       return {
           'id': self.id,
           'email': self.email,
           'username': self.username,
           'first_name': self.first_name,
           'last_name': self.last_name,
           'created_at': self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
           'last_login': self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
           'is_active': self.is_active,
           'is_admin': self.is_admin,
           'role': self.role,
           'is_google_user': self.is_google_user
       }

   def __repr__(self):
       return f'<User {self.username}>'