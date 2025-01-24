import os
import re
import logging
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, session, abort, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

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
# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class Config:
    SECRET_KEY = os.urandom(24)
    DEBUG = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB file upload limit

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

def create_app(config_class=DevelopmentConfig):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
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
    client = Client()
    image_to_text_client = Client(
        api_key="YOUR_API_KEY",
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

        # Validate the image type (only accept image files)
        if not allowed_file(image_file.filename):
            return "Invalid file type. Only image files are allowed."

        # Save the file securely
        filename = secure_filename(image_file.filename)
        logger.info(f"Processing image: {filename}")
        
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

def allowed_file(filename):
    """Check if the file has an allowed extension"""
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

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

def enforce_strict_format(raw_grade):
    """Enforce strict grading format: 'Grade: [score]/[total] Justification: [text]'."""
    raw_grade = raw_grade.replace("*", "").replace("_", "").strip()

    grade_pattern = re.compile(r"Grade:\s*([\d\.]+)\s*/\s*([\d\.]+)\s*Justification:\s*(.*)", re.DOTALL)

    match = grade_pattern.match(raw_grade)
    if not match:
        raise ValueError(f"Invalid grade format. Expected 'Grade: [score]/[total] Justification: [text]', got: {raw_grade}")

    score = float(match.group(1))
    total = float(match.group(2))
    justification = match.group(3).strip()

    if not justification:
        justification = "No justification provided."

    return f"Grade: {score}/{total} Justification: {justification}"

def grade_essay(essay_text, context_text):
    """Grade essay with robust error handling and logging"""
    try:
        if len(essay_text.split()) < 110:
            logger.warning("Essay too short for grading")
            return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 110 salita."

        criteria = session.get('criteria', [])
        if not criteria:
            logger.warning("No grading criteria set")
            return "No criteria set for grading."

        total_points_possible = sum(criterion['points_possible'] for criterion in criteria)
        if total_points_possible == 0:
            logger.warning("Total points possible is zero")
            return "No valid criteria to grade the essay."

        total_points_received = 0
        grades_per_criterion = []

        for criterion in criteria:
            truncated_essay = essay_text[:1000]  

            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Grade the following essay based on the criterion '{criterion['name']}' "
                            f"out of {criterion['points_possible']} points. "
                            "Do not be too strict. Consider context and criteria."
                            "Respond in Filipino and provide a high grade if deserved, based on each criterion. "
                            f"Essay:\n{truncated_essay}\n\n"
                            f"Context:\n{context_text}\n\n"
                            "Response format: "
                            f"Grade: [numeric value]/{criterion['points_possible']} Justification: [text]."
                        )
                    }]

                )

                raw_grade = preprocess_input(response.choices[0].message.content.strip())
                formatted_grade = enforce_strict_format(raw_grade)

                grade_match = re.search(r"Grade:\s*([\d\.]+)\s*/\s*([\d\.]+)", formatted_grade)
                points_received = float(grade_match.group(1))
                total_points = float(grade_match.group(2))

                if points_received > total_points:
                    logger.warning(f"Points received exceed total points for '{criterion['name']}'")
                    return f"Invalid grade for '{criterion['name']}': points received cannot exceed total points."

                grades_per_criterion.append(
                    f"Criterion: {criterion['name']} - Grade: {points_received}/{total_points}"
                )
                total_points_received += points_received

            except Exception as criterion_error:
                logger.error(f"Error processing criterion {criterion['name']}: {criterion_error}")
                return f"Error grading criterion: {criterion['name']}"

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
        return f"Final Grade: {letter_grade}\nTotal: {total_points_received}/{total_points_possible} points\n{justification_summary}"

    except Exception as e:
        logger.error(f"Essay grading error: {e}")
        return f"An error occurred while grading the essay: {str(e)}"


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
            context = preprocess_input(request.form.get('context', ''))
            
            if not context:
                return render_template('index.html', error="Context is required")

            image = request.files.get('image')
            essay = image_to_text(image) if image else preprocess_input(request.form.get('essay', ''))

            if len(essay.split()) < 110:
                return render_template('index.html', error="Essay must be at least 110 words")

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

    summary_result = generate_summary(original_text)
    graded_result = grade_essay(original_text, context_text)

    session['summary'] = summary_result
    session['grade'] = graded_result

    logger.info(f"Processed Essay Summary: {summary_result}")
    logger.info(f"Processed Essay Grade: {graded_result}")

    # Debugging to check the session values
    print("SESSION DATA:")
    print(f"Original Text: {original_text}")
    print(f"Context Text: {context_text}")
    print(f"Summary: {summary_result}")
    print(f"Grade: {graded_result}")

    return render_template('results.html', summary=summary_result, grade=graded_result)

@app.route('/set_criteria', methods=['GET', 'POST'])
def set_criteria():
    if request.method == 'POST':
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
        session.modified = True

        session['total_points_possible'] = sum(criterion['points_possible'] for criterion in session['criteria'])

        return redirect(url_for('set_criteria'))

    criteria = session.get('criteria', [])
    total_points_possible = session.get('total_points_possible', 0)

    return render_template('set_criteria.html', criteria=criteria, total_points_possible=total_points_possible)

@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.pop('criteria', None)
    session.pop('total_points_possible', None)
    return redirect(url_for('set_criteria'))

@app.route('/contact')
def contact():
    return redirect("https://www.facebook.com/profile.php?id=61571739043757")

@app.route('/how-to-use', methods=['GET'])
def how_to_use():
    return render_template('how_to_use.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
