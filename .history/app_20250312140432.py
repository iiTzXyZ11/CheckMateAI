import os
import re
import g4f
import g4f.Provider
from datetime import timedelta
from flask import Flask, render_template, redirect, url_for, request, session
from markupsafe import Markup

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Remove Flask-Markdown since it's causing issues with newer Flask versions

client = g4f.Client()
image_to_text_client = g4f.Client(provider=g4f.Provider.Blackbox)

def format_justification(justification):
    justification = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', justification)
    justification = re.sub(r'(\d+\.) ', r'<br>\1 ', justification)
    justification = justification.replace('\n', '<br>')
    return Markup(justification)

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

@app.route('/')
def home():
    return redirect(url_for('front_page'))

@app.route('/front')
def front_page():
    return render_template('front_page.html')

@app.route('/scan', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        student_name = request.form.get('student_name', '').strip()
        session['student_name'] = student_name
        print(f"Saving student name to session: {student_name}")

        context = request.form.get('context', '').strip()
        session['context_text'] = context

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

    context = session.get('context_text', '')
    print(f"Retrieved context from session: {context}")
    return render_template('index.html', context=context)

@app.route('/process_essay', methods=['POST'])
def process_essay():
    student_name = session.get('student_name', 'Unnamed Student')
    original_text = session.get('original_text', '')
    context_text = session.get('context_text', '')
    if not original_text or not context_text:
        print("Error: Missing original text or context in session.")
        return redirect(url_for('index'))

    summary_result = generate_summary(original_text)

    final_grade = "N/A"
    criteria_results = []

    print("Sending to template:", criteria_results)

    results_dir = os.path.join(app.root_path, 'static', 'results')
    os.makedirs(results_dir, exist_ok=True)

    results_filename = os.path.join(results_dir, f"{student_name}_results.txt")
    with open(results_filename, 'w', encoding='utf-8') as f:
        f.write(f"Student Name: {student_name}\n\n")
        f.write(f"Original Essay:\n{original_text}\n\n")
        f.write(f"Summary:\n{summary_result}\n\n")

    return render_template('results.html',
                         essay=original_text,
                         summary=summary_result,
                         final_grade=final_grade,
                         criteria_results=criteria_results,
                         context=context_text,
                         student_name=student_name)

@app.route('/contact')
def contact():
    return redirect("https://www.facebook.com/profile.php?id=61567870400304")

@app.route('/how-to-use', methods=['GET'])
def how_to_use():
    return render_template('how_to_use.html')

if __name__ == '__main__':
    app.run(debug=True)
