"""Flask API backend for Persistent Context Engine."""
from __future__ import annotations

import os
import json
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

from adapters.myteam import Engine

# Configure logging
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for Streamlit frontend

# Initialize engine
try:
    engine = Engine()
    logger.info("Engine initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize engine: {e}")
    engine = None


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "engine_ready": engine is not None}), 200


@app.route("/api/analyze", methods=["POST"])
def analyze_events():
    """
    Analyze events and return context reconstruction.
    
    Expected JSON payload:
    {
        "events": [
            {"id": "1", "service": "auth", "message": "Login failed", ...},
            ...
        ],
        "mode": "fast" or "deep",
        "signal": {"id": "signal-1", ...}
    }
    """
    try:
        if engine is None:
            return jsonify({"error": "Engine not initialized"}), 500

        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        events = data.get("events", [])
        mode = data.get("mode", "fast")
        signal = data.get("signal")

        if not events:
            return jsonify({"error": "No events provided"}), 400

        if not signal:
            return jsonify({"error": "No signal provided"}), 400

        # Call the engine to analyze
        result = engine.reconstruct_context(
            signal=signal,
            events=events,
            mode=mode
        )

        return jsonify({
            "success": True,
            "result": result,
            "mode": mode
        }), 200

    except Exception as e:
        logger.error(f"Error analyzing events: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/explain", methods=["POST"])
def explain_incident():
    """
    Generate explanation for an incident.
    
    Expected JSON payload:
    {
        "signal": {...},
        "related_events": [...],
        "causal_chain": [...],
        "similar_incidents": [...],
        "suggested_remediations": [...]
    }
    """
    try:
        if engine is None:
            return jsonify({"error": "Engine not initialized"}), 500

        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        explanation = engine.generate_explanation(
            signal=data.get("signal"),
            related_events=data.get("related_events", []),
            causal_chain=data.get("causal_chain", []),
            similar_incidents=data.get("similar_incidents", []),
            suggested_remediations=data.get("suggested_remediations", [])
        )

        return jsonify({
            "success": True,
            "explanation": explanation
        }), 200

    except Exception as e:
        logger.error(f"Error generating explanation: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def get_status():
    """Get API and engine status."""
    return jsonify({
        "api_version": "1.0",
        "engine_ready": engine is not None,
        "environment": os.environ.get("ENVIRONMENT", "development")
    }), 200


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
