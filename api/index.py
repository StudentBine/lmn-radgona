import os
import sys

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app_radgona import app
except ImportError as e:
    # If import fails, create a minimal Flask app to show the error
    from flask import Flask, jsonify
    app = Flask(__name__)
    
    @app.route('/')
    def error():
        return jsonify({'error': f'Failed to import app: {str(e)}'}), 500
