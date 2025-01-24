import os
import re
import logging
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, session, abort, Response
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from g4f.client import Client
from g4f.Provider import GeminiPro

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='checkmate_app.log'
)
logger = logging.getLogger(__name__)

class Config:
    SECRET_KEY = os.urandom(24)
    DEBUG = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB file upload limit

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

def get_secure_api_key(key_name):
    """Retrieve API key securely from environment"""
    api_key = os.getenv(key_name)
    if not api_key:
        logger.error(f"Missing API key for {key_name}")
        raise ValueError(f"API key {key_name} not found in environment")
    return api_key

def create_app(config_class=DevelopmentConfig):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # CSRF Protection
    csrf = CSRFProtect(app)
    
    # Rate Limiting
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["100 per day", "30 per hour"],
        storage_uri="memory://"
    )

    return app, limiter

# Unpack both app and limiter
app, limiter = create_app()

# Secure client initialization
try:
    client = Client(api_key=get_secure_api_key('GPT_API_KEY'))
    image_to_text_client = Client(
        api_key=get_secure_api_key('AIzaSyCX13POLxDWzFWzOfZr7rn3vjG0eNUXlfk'), 
        provider=GeminiPro
    )
except ValueError as e:
    logger.critical(str(e))
    raise

def sanitize_input(input_text):
    """Sanitize and validate input text"""
    if not isinstance(input_text, str):
        raise ValueError("Input must be a string")
    
    # Remove potentially harmful characters and excess whitespace
    sanitized_text = re.sub(r'[<>&]', '', input_text)
    return re.sub(r'\s+', ' ', sanitized_text.strip())

def preprocess_input(input_text):
    """Normalize and validate input"""
    try:
        return sanitize_input(input_text)
    except ValueError as e:
        logger.warning(f"Input preprocessing error: {e}")
        return ""

def image_to_text(image_file):
    """Convert image to text with robust error handling"""
    try:
        if not image_file:
            return "No image provided"

        logger.info(f"Processing image: {image_file.filename}")
        
        response = image_to_text_client.chat.completions.create(
            model="gemini-1.5-pro-latest",
            messages=[{"role": "user", "content": "extract the text from this image"}],
            image=image_file
        )
        
        if not response or not hasattr(response, 'choices') or len(response.choices) == 0:
            logger.warning("No text extracted from image")
            return "No text could be extracted."
        
        content = response.choices[0].message.content
        extracted_text = content.strip() if content else "No text could be extracted."
        
        logger.info(f"Successfully extracted text from image: {len(extracted_text)} characters")
        return extracted_text
    
    except Exception as e:
        logger.error(f"Image processing error: {type(e).__name__} - {str(e)}")
        return f"Image processing failed: {str(e)}"

def generate_summary(text):
    """Generate summary with improved error handling"""
    try:
        if len(text.split()) < 110:
            return "Error: Input text must be at least 110 words."

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Summarize this text in Filipino:\n\n{text}"}]
        )

        if not response.choices:
            logger.warning("No summary generated")
            return "No summary could be generated."

        summary_content = response.choices[0].message.content.strip()
        logger.info(f"Generated summary of {len(summary_content)} characters")
        return summary_content or "No summary could be generated."

    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        return f"An error occurred during summarization: {str(e)}"

def grade_essay(essay_text, context_text):
    """Grade essay with robust error handling and logging"""
    try:
        # Validate input length
        if len(essay_text.split()) < 110:
            logger.warning("Essay too short for grading")
            return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 110 salita."

        # Validate criteria
        criteria = session.get('criteria', [])
        if not criteria:
            logger.warning("No grading criteria set")
            return "No criteria set for grading."

        # Calculate total possible points
        total_points_possible = sum(criterion['points_possible'] for criterion in criteria)
        if total_points_possible == 0:
            logger.warning("Total points possible is zero")
            return "No valid criteria to grade the essay."

        total_points_received = 0
        grades_per_criterion = []

        # Compile regex patterns for grade validation
        grade_pattern = re.compile(r"Grade:\s*(\d+(?:\.\d+)?)\/(\d+)")
        justification_pattern = re.compile(r"Justification:\s*(.+)")

        # Process each grading criterion
        for criterion in criteria:
            # Truncate essay to prevent excessive token usage
            truncated_essay = essay_text[:1000]  

            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Grade the following essay based on the criterion '{criterion['name']}' "
                            f"out of {criterion['points_possible']} points. "
                            "Do not be too strict. Consider context and criteria carefully. "
                            "Respond in Filipino with an objective assessment. "
                            f"Essay:\n{truncated_essay}\n\n"
                            f"Context:\n{context_text}\n\n"
                            "Response format: "
                            f"Grade: [numeric value]/{criterion['points_possible']} Justification: [text]."
                        )
                    }]
                )

                # Validate response structure
                if not hasattr(response, 'choices') or len(response.choices) == 0:
                    logger.error(f"Invalid AI response for criterion: {criterion['name']}")
                    return f"Invalid response for criterion '{criterion['name']}'."

                # Process AI-generated grade
                raw_grade = preprocess_input(response.choices[0].message.content.strip())
                logger.info(f"Raw grade for {criterion['name']}: {raw_grade}")

                # Extract grade details
                grade_match = grade_pattern.search(raw_grade)
                justification_match = justification_pattern.search(raw_grade)

                if not grade_match or not justification_match:
                    logger.warning(f"Incorrect grade format: {raw_grade}")
                    return (f"Invalid grade format for '{criterion['name']}'. "
                            "Expected: 'Grade: [score]/[total] Justification: [text]'")

                # Parse grade components
                points_received = float(grade_match.group(1))
                justification = justification_match.group(1)

                # Record criterion grade
                grades_per_criterion.append(
                    f"Criterion: {criterion['name']} - Grade: {points_received}/{criterion['points_possible']} "
                    f"- Justification: {justification}"
                )
                total_points_received += points_received

            except Exception as criterion_error:
                logger.error(f"Error processing criterion {criterion['name']}: {criterion_error}")
                return f"Error grading criterion: {criterion['name']}"

        # Calculate final grade
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

        # Log grade details
        logger.info(f"Final Grade: {letter_grade}, Score: {total_points_received}/{total_points_possible}")

        # Prepare grade report
        justification_summary = "\n".join(grades_per_criterion)
        return (f"Draft Grade: {letter_grade}\n"
                f"Draft Score: {total_points_received}/{total_points_possible}\n\n"
                f"Justifications:\n{justification_summary}")

    except Exception as overall_error:
        logger.critical(f"Catastrophic grading error: {overall_error}")
        return "An unexpected error occurred during essay grading."

@app.route('/')
def home():
    logger.info("Home page accessed")
    return redirect(url_for('front_page'))

@app.route('/front')
def front_page():
    return render_template('front_page.html')

@app.route('/scan', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def index():
    try:
        if request.method == 'POST':
            # Input validation
            context = preprocess_input(request.form.get('context', ''))
            
            if not context:
                return render_template('index.html', error="Context is required")

            # Image or text processing
            image = request.files.get('image')
            essay = image_to_text(image) if image else preprocess_input(request.form.get('essay', ''))

            if len(essay.split()) < 110:
                return render_template('index.html', error="Essay must be at least 110 words")

            # Store in session securely
            session['original_text'] = essay
            session['context_text'] = context
            session.modified = True

            return redirect(url_for('set_criteria'))

        return render_template('index.html')

    except Exception as e:
        logger.error(f"Scan route error: {e}")
        abort(500)

@app.route('/process_essay', methods=['GET', 'POST'])
def process_essay():
    original_text = session.get('original_text', '')
    context_text = session.get('context_text', '')

    if not original_text or not context_text:
        return redirect(url_for('home'))

    # Generate summary
    summary_result = generate_summary(original_text)

    # Grade the essay based on criteria
    grade_result = grade_essay(original_text, context_text)

    return render_template('results.html', essay=original_text, summary=summary_result, grade=grade_result)

@app.route('/set_criteria', methods=['GET', 'POST'])
def set_criteria():
    if request.method == 'POST':
        # Retrieve the criterion details from the form
        criterion_name = request.form['criterion_name']
        weight = float(request.form['weight']) / 100  # Convert to fraction
        points_possible = float(request.form['points_possible'])
        detailed_breakdown = request.form['detailed_breakdown']

        # Create a new criterion entry
        new_criterion = {
            'name': criterion_name,
            'weight': weight,
            'points_possible': points_possible,
            'detailed_breakdown': detailed_breakdown
        }

        # Retrieve existing criteria from the session, or initialize if none exist
        if 'criteria' not in session:
            session['criteria'] = []
        session['criteria'].append(new_criterion)  # Add the new criterion
        session.modified = True  # Mark the session as modified

        # Recalculate total points possible
        session['total_points_possible'] = sum(criterion['points_possible'] for criterion in session['criteria'])

        return redirect(url_for('set_criteria'))  # Redirect to the same page to display updated criteria

    # Load existing criteria for the GET request
    criteria = session.get('criteria', [])
    total_points_possible = session.get('total_points_possible', 0)

    return render_template('set_criteria.html', criteria=criteria, total_points_possible=total_points_possible)

@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.pop('criteria', None)  # Remove the criteria data from the session
    session.pop('total_points_possible', None)  # Remove any other session data if needed
    return redirect(url_for('set_criteria'))  # Redirect to the set criteria page

@app.route('/contact')
def contact():
    return redirect("https://www.facebook.com/profile.php?id=61571739043757")

@app.route('/how-to-use', methods=['GET'])
def how_to_use():
    return render_template('how_to_use.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)