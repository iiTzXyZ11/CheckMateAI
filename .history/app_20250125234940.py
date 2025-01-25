import os
import re
import logging
from typing import Optional, Dict, Any, List

import flask
from flask import Flask, render_template, redirect, url_for, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from g4f.client import Client
from g4f.Provider import GeminiPro

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EssayGradingApp:
    def __init__(self):
        self.app = Flask(__name__)
        self._configure_app()
        self._setup_extensions()
        self._setup_routes()
        
        # Initialize clients with error handling
        try:
            self.text_client = Client()
            self.image_to_text_client = Client(
                provider=GeminiPro
            )
        except Exception as e:
            logger.error(f"Client initialization error: {e}")
            raise

    def _configure_app(self):
        # Use a random secret key with a fallback
        self.app.secret_key = os.urandom(24)
        self.app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
        )

    def _setup_extensions(self):
        
        # Add rate limiting
        self.limiter = Limiter(
            get_remote_address,
            app=self.app,
            default_limits=["100 per day", "30 per hour"]
        )

    def _setup_routes(self):
        # Home route
        @self.app.route('/')
        def home():
            logger.info("Home page accessed")
            return redirect(url_for('front_page'))

        # Front page route
        @self.app.route('/front')
        def front_page():
            logger.info("Front page accessed")
            return render_template('front_page.html')

        # Scanning route
        @self.app.route('/scan', methods=['GET', 'POST'])
        def index():
            if request.method == 'POST':
                return self.handle_essay_upload()
            return render_template('index.html')

        # Criteria setting route
        @self.app.route('/set_criteria', methods=['GET', 'POST'])
        def set_criteria():
            if request.method == 'POST':
                return self.handle_criterion_addition()
            
            criteria = session.get('criteria', [])
            total_points_possible = session.get('total_points_possible', 0)
            return render_template('set_criteria.html', 
                                   criteria=criteria, 
                                   total_points_possible=total_points_possible)

        # Essay processing route
        @self.app.route('/process_essay', methods=['GET', 'POST'])
        def process_essay():
            original_text = session.get('original_text', '')
            context_text = session.get('context_text', '')

            if not original_text or not context_text:
                return redirect(url_for('home'))

            summary_result = self.generate_summary(original_text)
            grade_result = self.grade_essay(original_text, context_text)

            return render_template('results.html', 
                                   essay=original_text, 
                                   summary=summary_result, 
                                   grade=grade_result)

        # Session clearing route
        @self.app.route('/clear_session', methods=['POST'])
        def clear_session():
            session.pop('criteria', None)
            session.pop('total_points_possible', None)
            return redirect(url_for('set_criteria'))

        # Contact route
        @self.app.route('/contact')
        def contact():
            return redirect("https://www.facebook.com/profile.php?id=61567870400304")

        # How to use route
        @self.app.route('/how-to-use')
        def how_to_use():
            return render_template('how_to_use.html')

    def handle_essay_upload(self):
        context = request.form['context']
        session['context_text'] = context

        # Check for image upload
        image = request.files.get('image')
        if image:
            essay = self.safe_image_to_text(image)
            if "Error" in essay:
                return render_template('index.html', error=essay)
        else:
            essay = request.form['essay']

        session['original_text'] = essay

        # Validate input
        if not self.validate_input(essay):
            return render_template('index.html', 
                                   essay=essay,
                                   error="Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 150 salita.")

        if not context.strip():
            return render_template('index.html', 
                                   essay=essay,
                                   error="Error: Please provide context for grading.")

        return redirect(url_for('set_criteria'))

    def handle_criterion_addition(self):
        try:
            criterion_name = request.form['criterion_name']
            weight = float(request.form['weight']) / 100
            points_possible = float(request.form['points_possible'])
            detailed_breakdown = request.form['detailed_breakdown']

            new_criterion = {
                'name': criterion_name,
                'weight': weight,
                'points_possible': points_possible,
                'detailed_breakdown': detailed_breakdown
            }

            if 'criteria' not in session:
                session['criteria'] = []
            
            session['criteria'].append(new_criterion)
            

            session['total_points_possible'] = sum(
                criterion['points_possible'] for criterion in session['criteria']
            )

            return redirect(url_for('set_criteria'))
        except Exception as e:
            logger.error(f"Error adding criterion: {e}")
            return render_template('set_criteria.html', error="Error adding criterion")

    def validate_input(self, text: str, min_length: int = 150) -> bool:
        """Validate input text based on length."""
        return len(text.split()) >= min_length

    def safe_image_to_text(self, image_file) -> str:
        """Safely convert image to text with comprehensive error handling."""
        try:
            response = self.image_to_text_client.chat.completions.create(
                model="gemini-1.5-pro-latest",
                messages=[{"role": "user", "content": "extract the text from this image"}],
                image=image_file
            )
            
            if response and hasattr(response, 'choices') and response.choices:
                return response.choices[0].message.content.strip() or "No text extracted"
            
            return "No text could be extracted"
        
        except Exception as e:
            logger.error(f"Image to text conversion error: {e}")
            return f"Error processing image: {str(e)}"

    def generate_summary(self, text: str) -> str:
        """Generate summary with error handling."""
        if len(text.split()) < 150:
            return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 150 salita."

        try:
            response = self.text_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": f"Summarize this text in Filipino:\n\n{text}"}]
            )

            if not response.choices:
                logger.warning("No choices in response for summary")
                return "No summary could be generated."

            summary_content = response.choices[0].message.content.strip()
            return summary_content or "No summary could be generated."

        except Exception as e:
            logger.error(f"Error during summary generation: {e}")
            return f"An error occurred during summarization: {str(e)}"

    def grade_essay(self, essay_text: str, context_text: str) -> str:
        """Grade essay with comprehensive error handling."""
        if len(essay_text.split()) < 150:
            return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 150 salita."

        criteria = session.get('criteria', [])
        if not criteria:
            return "No criteria set for grading."

        total_points_possible = session.get('total_points_possible', 0)
        if total_points_possible == 0:
            return "No valid criteria to grade the essay."

        total_points_received = 0
        grades_per_criterion = []
        
        grade_pattern = re.compile(r"Grade:\s*(\d+(\.\d+)?)\/(\d+)")
        justification_pattern = re.compile(r"Justification:\s*(.*)")

        for criterion in criteria:
            truncated_essay = essay_text[:1000]

            try:
                response = self.text_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{
                        "role": "user",
                        "content": (f"Grade the following essay based on the criterion '{criterion['name']}' out of "
                            f"{criterion['points_possible']} points. Please be consistent and fair in your grading, "
                            "focusing on the specific aspects of the essay that correspond to the given criterion. "
                            "Do not be overly lenient but also avoid being strict. Ensure the grading is based on the "
                            "clarity, depth, and relevance of the content. Consider the context and parameters provided, "
                            "Respond in Filipino and provide a high grade if the essay meets the criterion , but "
                            "maintain consistency across grading for different essays with the same conditions. "
                            f"Essay:\n{truncated_essay}\n\n"
                            f"Context:\n{context_text}\n\n"
                            "follow the grading format and provide both the grade and a detailed justification: "
                            f"Grade: [numeric value]/{criterion['points_possible']} Justification: [text]. "
                            "Ensure the justification is specific to the essay's performance in relation to the criterion.")
                    }]
                )

                if not hasattr(response, 'choices') or len(response.choices) == 0:
                    return f"Invalid response for criterion '{criterion['name']}'."

                raw_grade = response.choices[0].message.content.strip()

                grade_match = grade_pattern.search(raw_grade)
                justification_match = justification_pattern.search(raw_grade)

                points_received = float(grade_match.group(1)) if grade_match else 0
                justification = justification_match.group(1) if justification_match else "No justification"

                total_points_received += points_received
                grades_per_criterion.append(
                    f"Criterion: {criterion['name']} - "
                    f"Grade: {points_received}/{criterion['points_possible']} - "
                    f"Justification: {justification}"
                )

            except Exception as e:
                logger.error(f"Grading error for {criterion['name']}: {e}")
                return f"Error grading criterion: {criterion['name']}"

        # Calculate percentage and letter grade
        percentage = (total_points_received / total_points_possible) * 100
        letter_grade = (
            "A+" if percentage >= 98 else
            "A" if percentage >= 95 else
            "A-" if percentage >= 93 else
            "B+" if percentage >= 90 else
            "B" if percentage >= 85 else
            "B-" if percentage >= 83 else
            "C+" if percentage >= 80 else
            "C" if percentage >= 78 else
            "D" if percentage >= 75 else "F"
        )

        justification_summary = "\n".join(grades_per_criterion)

        return (
            f"Draft Grade: {letter_grade}\n"
            f"Draft Score: {total_points_received}/{total_points_possible}\n\n"
            f"Justifications:\n{justification_summary}"
        )

    def run(self, debug: bool = False):
        """Run the Flask application."""
        try:
            self.app.run(
                host='0.0.0.0',
                port=5000,
                debug=debug
            )
        except Exception as e:
            logger.critical(f"Application startup failed: {e}")
            raise

def create_app():
    """Factory function to create and configure the Flask app."""
    essay_app = EssayGradingApp()
    return essay_app.app