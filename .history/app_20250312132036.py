import os
import re
import g4f
import g4f.Provider
from datetime import timedelta
from flask import Flask, render_template, redirect, url_for, request, session
from markdown2 import markdown
@app.template_filter('markdown')
def markdown_filter(text):
    return markdown(text)

app.jinja_env.filters['markdown'] = markdown_filter  # Register filter Register Markdown with Flask

app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)


client = g4f.Client()
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
    
    # Define regex patterns
    grade_pattern = re.compile(r"Grade:\s*(\d+(\.\d+)?)\/(\d+)")
    justification_pattern = re.compile(r"Justification:\s*(.*)")

    for criterion in criteria:
        truncated_essay = essay_text[:1000]  # Avoid too long prompts

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": (
                    f"Grade the following student work based on the criterion '{criterion['name']}' out of {criterion['points_possible']} points.\n\n"
                    f"Context from teacher: {context_text}\n\n"
                    "When grading, consider:\n"
                    f"1. How well the student addresses the specific requirements of '{criterion['name']}'\n"
                    "2. Both the strengths and areas for improvement in the student's work\n"
                    "3. The depth of understanding demonstrated, not just surface-level content\n"
                    "4. The appropriate use of concepts and terminology related to the topic\n\n"
                    "ALWAYS respond in Filipino with a fair assessment. Only assign a failing grade if the student work shows no clear connection to the required topic or criterion.\n\n"
                    f"Essay to grade: {truncated_essay}\n\n"
                    "Your response should follow this format:\n"
                    f"Grade: [numeric value]/{criterion['points_possible']}\n"
                    "Justification: [Provide specific examples from the student's work that justify your grade (cite lines from the student's work to support your grading). Mention both positive aspects and areas for improvement.]"
                )
            }]
        )


        if not hasattr(response, 'choices') or len(response.choices) == 0:
            return f"Invalid response received for criterion '{criterion['name']}'. No choices were found."

        raw_grade = response.choices[0].message.content.strip()
        print(f"Raw grade for {criterion['name']}: {raw_grade}")

        # Extract Grade
        grade_match = grade_pattern.search(raw_grade)
        points_received = float(grade_match.group(1)) if grade_match else 0

        # Extract Justification
        justification_match = justification_pattern.search(raw_grade)
        justification = justification_match.group(1) if justification_match else "No justification provided."

        # Store results
        justifications[criterion['name']] = justification
        total_points_received += points_received
        grades_per_criterion.append(f"Criterion: {criterion['name']} - Grade: {points_received}/{criterion['points_possible']} - Justification: {justification}")

    # Final Computation and Result Formatting
    final_grade = f"{total_points_received}/{total_points_possible}"
    result_summary = "\n".join(grades_per_criterion)

    return f"Final Grade: {final_grade}\n\n{result_summary}"

@app.route('/')
def home():
    return redirect(url_for('front_page'))

@app.route('/front')
def front_page():
    return render_template('front_page.html')

@app.route('/scan', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Get student name from the form and store in session
        student_name = request.form.get('student_name', '').strip()
        session['student_name'] = student_name
        print(f"Saving student name to session: {student_name}")  # Debug print

        context = request.form.get('context', '').strip()
        session['context_text'] = context
        
        # Handling the image or essay input as before...
        image = request.files.get('image')
        if image:
            essay = image_to_text(image)
            if "Error" in essay:
                return render_template('index.html', error=essay, context=context)
        else:
            essay = request.form.get('essay', '')

        session['original_text'] = essay
        
        if len(essay.split()) < 20:
            return render_template('index.html', essay=essay, context=context, error="Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita.")

        if not context:
            return render_template('index.html', essay=essay, context=context, error="Error: Please provide context for grading.")

        return redirect(url_for('set_criteria'))

    # For GET requests
    context = session.get('context_text', '')
    print(f"Retrieved context from session: {context}")  # Debug print
    return render_template('index.html', context=context)

@app.route('/set_criteria', methods=['GET', 'POST'])
def set_criteria():
    # Get context from session
    context = session.get('context_text', '')
    
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
                         context=context)

@app.route('/process_essay', methods=['POST'])
def process_essay():
    student_name = session.get('student_name', 'Unnamed Student')
    original_text = session.get('original_text', '')
    context_text = session.get('context_text', '')
    if not original_text or not context_text:
        print("Error: Missing original text or context in session.")
        return redirect(url_for('index'))

    summary_result = generate_summary(original_text)
    grade_result = grade_essay(original_text, context_text)

    # Parse the grade result
    grade_lines = grade_result.split('\n')
    final_grade = grade_lines[0] if grade_lines else 'N/A'
    
    # Extract individual criterion grades and justifications
    criteria_results = []
    current_criterion = {}
    
    for line in grade_lines[2:]:  # Skip the empty line after final grade
        if line.strip():
            if line.startswith('Criterion:'):
                # Parse the line that contains criterion info
                parts = line.split(' - ')
                if len(parts) >= 3:
                    criterion_name = parts[0].replace('Criterion:', '').strip()
                    grade = parts[1].replace('Grade:', '').strip()
                    justification = parts[2].replace('Justification:', '').strip()
                    
                    criteria_results.append({
                        'name': criterion_name,
                        'grade': grade,
                        'justification': justification
                    })

    # Create results directory and save file
    results_dir = os.path.join(app.root_path, 'static', 'results')
    os.makedirs(results_dir, exist_ok=True)

    results_filename = os.path.join(results_dir, f"{student_name}_results.txt")
    with open(results_filename, 'w', encoding='utf-8') as f:
        f.write(f"Student Name: {student_name}\n\n")
        f.write(f"Original Essay:\n{original_text}\n\n")
        f.write(f"Summary:\n{summary_result}\n\n")
        f.write(f"Grade:\n{grade_result}\n")

    return render_template('results.html',
                         essay=original_text,
                         summary=summary_result,
                         final_grade=final_grade,
                         grade=final_grade or "N/A",
                         criteria_results=criteria_results,
                         context=context_text,
                         student_name=student_name)

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