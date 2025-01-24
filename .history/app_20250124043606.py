import os  # Standard library
import re
import logging
from flask import Flask, render_template, redirect, url_for, request, session
from dotenv import load_dotenv
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from g4f.client import Client  # GPT-based client
from g4f.Provider import GeminiPro

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='checkmate_app.log'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a random secret key

# Initialize the GPT client for text generation and grading
client = Client()
image_to_text_client = Client(api_key="AIzaSyCX13POLxDWzFWzOfZr7rn3vjG0eNUXlfk", provider=GeminiPro)

# Helper function for preprocessing input
def preprocess_input(input_text):
    """Normalize input by stripping extra spaces and newlines."""
    return re.sub(r'\s+', ' ', input_text.strip())

# Function to convert image to text
def image_to_text(image_file):
    try:
        print(f"Received the image: {image_file.filename}")
        response = image_to_text_client.chat.completions.create(
            model="gemini-1.5-pro-latest",
            messages=[{"role": "user", "content": "extract the text from this image"}],
            image=image_file
        )
        if hasattr(response, 'choices') and len(response.choices) > 0:  # type: ignore
            content = response.choices[0].message.content  # type: ignore
            print(f"Extracted content: {content}")
            return content.strip() if content else "No text could be extracted."
        return "No text could be extracted."
    except Exception as e:
        print(f"Error during image processing: {e}")
        return f"An error occurred during image processing: {str(e)}"

# Function to summarize text in Filipino
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

# Grade essay function
def grade_essay(essay_text, context_text):
    # Check essay length early
    if len(essay_text.split()) < 110:
        return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 110 salita."

    criteria = session.get('criteria', [])
    if not criteria:
        return "No criteria set for grading."

    total_points_possible = session.get('total_points_possible', 0)
    if total_points_possible == 0:
        return "No valid criteria to grade the essay."

    total_points_received = 0
    grades_per_criterion = []

    # Compile regex patterns with flexibility
    grade_pattern = re.compile(r"Grade:\s*(\d+(?:\.\d+)?)\/(\d+)")
    justification_pattern = re.compile(r"Justification:\s*(.+)")

    for criterion in criteria:
        truncated_essay = essay_text[:1000]  # Limit essay length for context

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": (f"Grade the following essay based on the criterion '{criterion['name']}' out of "
                            f"{criterion['points_possible']} points. "
                            "Do not be too strict when grading. Consider the context and criteria. "
                            "Respond in Filipino and provide a high grade if deserved, based on the criterion. "
                            f"Essay:\n{truncated_essay}\n\n"
                            f"Context:\n{context_text}\n\n"
                            "Strictly provide the response in this format: "
                            f"Grade: [numeric value]/{criterion['points_possible']} Justification: [text].")
            }]
        )

        if not hasattr(response, 'choices') or len(response.choices) == 0:  # type: ignore
            return f"Invalid response for criterion '{criterion['name']}'. No choices found."

        raw_grade = preprocess_input(response.choices[0].message.content.strip())  # type: ignore
        print(f"Raw grade for {criterion['name']}: {raw_grade}")  # Debug print

        # Validate using regex
        grade_match = grade_pattern.search(raw_grade)
        justification_match = justification_pattern.search(raw_grade)

        if not grade_match or not justification_match:
            print(f"Invalid format: {raw_grade}")
            return (f"Invalid grade format for criterion '{criterion['name']}'. "
                    "Expected format: 'Grade: [score]/[total] Justification: [text]'")

        points_received = float(grade_match.group(1))
        justification = justification_match.group(1)

        grades_per_criterion.append(
            f"Criterion: {criterion['name']} - Grade: {points_received}/{criterion['points_possible']} "
            f"- Justification: {justification}"
        )
        total_points_received += points_received

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

    return (f"Draft Grade: {letter_grade}\n"
            f"Draft Score: {total_points_received}/{total_points_possible}\n\n"
            f"Justifications:\n{justification_summary}")

@app.route('/')
def home():
    logger.info("Home page accessed")
    return redirect(url_for('front_page'))

@app.route('/front')  # Front page route
def front_page():
    print("Front page accessed")  # Debug print
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


@app.route('/process_essay', methods=['GET', 'POST'])  # Define the route for processing the essay
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


# New route for 'Contact Us'
@app.route('/contact')  # Define the contact route
def contact():
    return redirect("https://www.facebook.com/profile.php?id=61571739043757")  # Replace with your actual Facebook page URL

# New route for 'How to Use'
@app.route('/how-to-use', methods=['GET'])
def how_to_use():
    return render_template('how_to_use.html')

if __name__ == '__main__':
    app.run(debug=True)