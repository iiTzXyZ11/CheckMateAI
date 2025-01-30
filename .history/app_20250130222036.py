import os
import re
import g4f
import g4f.Provider
from flask import Flask, render_template, redirect, url_for, request, session
from g4f.client import Client
from datetime import timedelta

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # Session lasts 30 minutes

client = Client()
image_to_text_client = g4f.Client(provider=g4f.Provider.Blackbox)

def image_to_text(image_file):
    try:
        print(f"Received the image: {image_file.filename}")
        images = [[image_file, image_file.filename]]
        response = image_to_text_client.chat.completions.create(
            messages=[{
                "content": (
                    "Extract only the plain text from this image. "
                    "Do not use any special symbols like # or *. "
                    "If there are crossed-out words, ignore them as they are erasures. "
                    "Only include the readable text without any formatting."
                ),
                "role": "user"
            }],
            model="",
            images=images
        )

        if hasattr(response, 'choices') and len(response.choices) > 0:
            content = response.choices[0].message.content
            sanitized_content = content.replace("#", "").replace("*", "").strip()
            print(f"Extracted content: {sanitized_content}")
            return sanitized_content if sanitized_content else "No text could be extracted."
        return "No text could be extracted."

    except Exception as e:
        print(f"Error during image processing: {e}")
        return f"An error occurred during image processing: {str(e)}"

def generate_summary(text):
    if len(text.split()) < 20:
        return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita."

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Summarize this text in Filipino:\n\n{text}"}]
        )

        if not response.choices:
            print("No choices in response for summary.")
            return "No summary could be generated."

        summary_content = response.choices[0].message.content.strip()
        print(f"Generated summary: {summary_content}")
        return summary_content or "No summary could be generated."

    except Exception as e:
        print(f"Error during summary generation: {e}")
        return f"An error occurred during summarization: {str(e)}"

def grade_essay(essay_text, context_text):
    if len(essay_text.split()) < 20:
        return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita."

    criteria = session.get('criteria', [])
    if not criteria:
        return "No criteria set for grading."

    total_points_possible = session.get('total_points_possible', 0)
    if total_points_possible == 0:
        return "No valid criteria to grade the essay."

    total_points_received = 0
    justifications = {}
    grades_per_criterion = []
    
    grade_pattern = re.compile(r"Grade:\s*(\d+(\.\d+)?)\/(\d+)")
    justification_pattern = re.compile(r"Justification:\s*(.*)")

    for criterion in criteria:
        truncated_essay = essay_text[:1000]

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": (f"Grade the following student work based on the criterion '{criterion['name']}' out of "
                    f"{criterion['points_possible']} points. Please be consistent and fair in your grading, "
                    "focusing on the specific aspects of the essay that correspond to the given criterion. "
                    "Do not be overly lenient but also avoid being strict. Ensure the grading is based on the "
                    "clarity, depth, and relevance of the content. Consider the context and parameters provided, "
                    "Respond in Filipino and provide a high grade if the essay meets the criterion , but "
                    "maintain consistency across grading for different essays with the same conditions. "
                    "ONLY GIVE a low grade (Failing Scores) IF the points and topic discussed in the student work has no connection to the context and criteria."
                    f"Essay:\n{truncated_essay}\n\n"
                    f"Context:\n{context_text}\n\n"
                    "follow the grading format and provide both the grade and a detailed justification: "
                    f"Grade: [numeric value]/{criterion['points_possible']} Justification: [text]. "
                    "Ensure the justification is specific to the essay's performance in relation to the criterion.")
            }]
        )

        if not hasattr(response, 'choices') or len(response.choices) == 0:
            return f"Invalid response received for criterion '{criterion['name']}'. No choices were found."

        raw_grade = response.choices[0].message.content.strip()
        print(f"Raw grade for {criterion['name']}: {raw_grade}")

        grade_match = grade_pattern.search(raw_grade)
        justification_match = justification_pattern.search(raw_grade)

        if not grade_match:
            points_received = 0
        else:
            points_received = float(grade_match.group(1))

        if not justification_match:
            justification = "No justification provided."
        else:
            justification = justification_match.group(1)

        justifications[criterion['name']] = justification
        total_points_received += points_received

        grades_per_criterion.append(f"Criterion: {criterion['name']} - Grade: {points_received}/{criterion['points_possible']} - Justification: {justification}")

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
    return redirect(url_for('front_page'))

@app.route('/front')
def front_page():
    return render_template('front_page.html')

@app.route('/scan', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Get context from form and store in session
        context = request.form.get('context', '').strip()
        session['context_text'] = context
        print(f"Saving context to session: {context}")  # Debug print
        
        image = request.files.get('image')
        if image:
            essay = image_to_text(image)
            if "Error" in essay:
                return render_template('index.html', 
                                    error=essay, 
                                    context=context)  # Use the context we just got
        else:
            essay = request.form.get('essay', '')

        session['original_text'] = essay
        
        if len(essay.split()) < 20:
            return render_template('index.html', 
                                essay=essay, 
                                context=context,  # Use the context we just got
                                error="Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita.")

        if not context:
            return render_template('index.html', 
                                essay=essay, 
                                context=context,  # Use the context we just got
                                error="Error: Please provide context for grading.")

        return redirect(url_for('set_criteria'))

    # For GET requests
    context = session.get('context_text', '')
    print(f"Retrieved context from session: {context}")  # Debug print
    return render_template('index.html', context=context)
@app.route('/set_criteria', methods=['GET', 'POST'])
def set_criteria():
    if 'original_text' not in session or 'context_text' not in session:
        return redirect(url_for('index'))

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

        session['total_points_possible'] = sum(
            criterion['points_possible'] for criterion in session['criteria']
        )

        return redirect(url_for('set_criteria'))

    criteria = session.get('criteria', [])
    total_points_possible = session.get('total_points_possible', 0)
    
    return render_template('set_criteria.html', 
                         criteria=criteria,
                         total_points_possible=total_points_possible,
                         context=session.get('context_text', ''))

@app.route('/process_essay', methods=['POST'])
def process_essay():
    original_text = session.get('original_text', '')
    context_text = session.get('context_text', '')

    if not original_text or not context_text:
        return redirect(url_for('index'))

    summary_result = generate_summary(original_text)
    grade_result = grade_essay(original_text, context_text)

    return render_template('results.html',
                         essay=original_text,
                         summary=summary_result,
                         grade=grade_result,
                         context=context_text)

@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.pop('criteria', None)
    session.pop('total_points_possible', None)
    return redirect(url_for('set_criteria'))

@app.route('/contact')
def contact():
    return redirect("https://www.facebook.com/profile.php?id=61567870400304")

@app.route('/how-to-use', methods=['GET'])
def how_to_use():
    return render_template('how_to_use.html')

if __name__ == '__main__':
    app.run(debug=True)