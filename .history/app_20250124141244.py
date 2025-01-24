import os
import re
import logging
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, session, abort, Response
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
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

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
    
    # Removed CSRF Protection
    # csrf = CSRFProtect(app)  # Comment out or remove this line
    
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
        api_key="AIzaSyCX13POLxDWzFWzOfZr7rn3vjG0eNUXlfk",
        provider=GeminiPro
        )
    
except ValueError as e:
    logger.critical(str(e))
    raise

def preprocess_input(input_text, max_length=2000):
    """Robust input preprocessing with length limitation"""
    if not isinstance(input_text, str):
        return ""
    
    # Remove special characters and extra whitespace
    cleaned_text = re.sub(r'[^\w\s.,!?\'"-]', '', input_text)
    # Normalize whitespace
    normalized_text = ' '.join(cleaned_text.split())
    
    # Truncate to prevent excessive processing
    return normalized_text[:max_length]

def sanitize_input(input_text):
    """Enhanced input sanitization"""
    if not isinstance(input_text, str):
        raise ValueError("Input must be a string")
    
    # More efficient sanitization
    sanitization_table = str.maketrans({
        '<': '', 
        '>': '', 
        '&': ''
    })
    
    # Strip, translate, and normalize whitespace in one pass
    return ' '.join(input_text.translate(sanitization_table).split())

def image_to_text(image_file):
    """Optimized image text extraction with fallback"""
    try:
        if not image_file:
            return "No image provided"

        # Limit image size to prevent long processing
        image_file.seek(0, os.SEEK_END)
        file_size = image_file.tell()
        image_file.seek(0)

        # Reject files larger than 5MB
        if file_size > 5 * 1024 * 1024:
            return "Image too large. Maximum 5MB allowed."

        response = image_to_text_client.chat.completions.create(
            model="gemini-1.5-pro-latest",
            messages=[{
                "role": "user", 
                "content": "Extract key text from this image. Focus on main content."
            }],
            image=image_file
        )
        
        extracted_text = response.choices[0].message.content.strip() if response.choices else ""
        
        return extracted_text or "No text could be extracted."
    
    except Exception as e:
        logger.error(f"Image processing error: {type(e).__name__} - {str(e)}")
        return "Image processing failed. Please try again."

def generate_summary(text, max_words=300):
    """Efficient summary generation with length control"""
    # Validate input length
    if len(text.split()) < 110:
        return "Input text is too short for summarization."

    try:
        # Truncate input to prevent excessive token usage
        truncated_text = ' '.join(text.split()[:max_words])

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user", 
                "content": f"Create a concise summary in Filipino. Capture the main ideas succinctly:\n\n{truncated_text}"
            }]
        )

        summary = response.choices[0].message.content.strip()
        return summary or "Could not generate summary."

    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        return "Summary generation encountered an error."

def grade_essay(essay_text, context_text):
    """Refined essay grading with improved efficiency"""
    # Early validation checks
    if len(essay_text.split()) < 110:
        return "Essay is too short for comprehensive grading."

    # Retrieve and validate grading criteria
    criteria = session.get('criteria', [])
    
    # Log the criteria for debugging
    logger.info(f"Retrieved criteria: {criteria}")
    
    if not criteria:
        return "No grading criteria have been established."

    try:
        total_points_possible = sum(criterion['points_possible'] for criterion in criteria)
        if total_points_possible == 0:
            return "Invalid grading setup: No point values defined."

        # Prepare detailed grading prompt
        grading_prompt = (
            "Carefully evaluate this essay across multiple dimensions. "
            "Provide a precise, fair, and constructive assessment. "
            "Format your response as: 'Criterion Name: Points/Total - Specific Feedback'"
        )

        # Truncate inputs to manage processing time
        truncated_essay = ' '.join(essay_text.split()[:500])
        truncated_context = ' '.join(context_text.split()[:200])

        # Batch AI grading request
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": f"{grading_prompt}\n\n"
                          f"Essay: {truncated_essay}\n\n"
                          f"Context: {truncated_context}\n\n"
                          f"Grading Criteria: {', '.join([c['name'] for c in criteria])}"
            }]
        )

        # Process AI response
        ai_feedback = response.choices[0].message.content.strip()
        
        # Intelligent grade calculation
        total_points_received = 0
        detailed_feedback = []

        for criterion in criteria:
            # Extract criterion-specific feedback
            criterion_pattern = re.compile(
                f"{criterion['name']}:\\s*(\\d+(?:\\.\\d+)?)/({criterion['points_possible']})"
            )
            match = criterion_pattern.search(ai_feedback)
            
            if match:
                points = float(match.group(1))
                total_points_received += points
                detailed_feedback.append(
                    f"• {criterion['name']}: {points}/{criterion['points_possible']}"
                )

        # Calculate percentage and letter grade
        percentage = (total_points_received / total_points_possible) * 100
        letter_grade = (
            "A+" if percentage >= 97 else
            "A" if percentage >= 93 else
            "A-" if percentage >= 90 else
            "B+" if percentage >= 87 else
            "B" if percentage >= 83 else
            "B-" if percentage >= 80 else
            "C+" if percentage >= 77 else
            "C" if percentage >= 73 else
            "D" if percentage >= 70 else "F"
        )

        # Construct detailed grade report
        return (
            f"Overall Grade: {letter_grade}\n"
            f"Score: {total_points_received:.2f}/{total_points_possible}\n\n"
            "Detailed Feedback:\n" + 
            "\n".join(detailed_feedback)
        )

    except Exception as e:
        logger.error(f"Comprehensive grading error: {e}")
        return "Grading process encountered an unexpected error."

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

        # Log current criteria for debugging
        logger.info(f"Current criteria in session: {session.get('criteria')}")

        return redirect(url_for('set_criteria'))  # Redirect to the same page to display updated criteria

    # Load existing criteria for the GET request
    criteria = session.get('criteria', [])
    total_points_possible = session.get('total_points_possible', 0)

    return render_template('set_criteria.html', criteria=criteria, total_points_possible=total_points_possible)


@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.clear()
    return redirect(url_for('set_criteria'))


@app.route('/contact')
def contact():
    return redirect("https://www.facebook.com/profile.php?id=61571739043757")

@app.route('/how-to-use', methods=['GET'])
def how_to_use():
    return render_template('how_to_use.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)