from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import pandas as pd
import praw
from datetime import datetime
import os
import threading
from io import BytesIO
import socket
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')  # Change this in production

# ---------------- Reddit API setup ----------------
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.getenv('REDDIT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', 'RedditKeywordSearchBot/1.0')

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# Global variable to store search progress
search_progress = {
    'current': 0,
    'total': 0,
    'message': '',
    'is_running': False,
    'results': None,
    'error': None,
    'search_id': None
}

def get_local_ip():
    """Get the local IP address of the machine"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except:
        return "127.0.0.1"

def search_reddit(keywords, search_id):
    global search_progress
    results = []
    total = len(keywords)
    
    search_progress['total'] = total
    search_progress['current'] = 0
    search_progress['is_running'] = True
    search_progress['error'] = None
    search_progress['search_id'] = search_id
    search_progress['results'] = None
    
    try:
        for i, keyword in enumerate(keywords, start=1):
            search_progress['current'] = i
            search_progress['message'] = f"Searching for: {keyword}"
            
            try:
                for submission in reddit.subreddit("all").search(keyword, sort="top", limit=10):
                    results.append({
                        "Keyword": keyword,
                        "Title": submission.title,
                        "Subreddit": submission.subreddit.display_name,
                        "Score": submission.score,
                        "Comments": submission.num_comments,
                        "URL": submission.url,
                        "Created_UTC": datetime.fromtimestamp(submission.created_utc).strftime('%Y-%m-%d %H:%M:%S')
                    })
            except Exception as e:
                print(f"Error while searching for '{keyword}': {e}")
                continue
        
        search_progress['results'] = results
        search_progress['is_running'] = False
        return results
        
    except Exception as e:
        search_progress['error'] = str(e)
        search_progress['is_running'] = False
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global search_progress
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file selected'})
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'error': 'Please upload an Excel file (.xlsx or .xls)'})
    
    try:
        df = pd.read_excel(file)
        if "Keyword" not in df.columns:
            return jsonify({'success': False, 'error': "Excel file must have a 'Keyword' column"})
        
        keywords = df["Keyword"].dropna().tolist()
        
        if not keywords:
            return jsonify({'success': False, 'error': "No keywords found in the Excel file"})
        
        # Generate a unique search ID
        search_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Start search in background thread
        thread = threading.Thread(target=search_reddit, args=(keywords, search_id))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'search_id': search_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error reading file: {str(e)}'})

@app.route('/progress')
def progress():
    return render_template('index.html')

@app.route('/progress_data')
def progress_data():
    global search_progress
    return jsonify({
        'current': search_progress['current'],
        'total': search_progress['total'],
        'message': search_progress['message'],
        'is_running': search_progress['is_running'],
        'has_results': search_progress['results'] is not None,
        'error': search_progress['error'],
        'search_id': search_progress['search_id']
    })

@app.route('/results')
def show_results():
    global search_progress
    
    if search_progress['results'] is None:
        flash('No results available. Please run a search first.', 'error')
        return redirect(url_for('index'))
    
    results = search_progress['results']
    return render_template('results.html', results=results, total_results=len(results))

@app.route('/download')
def download_results():
    global search_progress
    
    if search_progress['results'] is None:
        flash('No results available to download', 'error')
        return redirect(url_for('index'))
    
    # Create Excel file in memory
    output = BytesIO()
    df = pd.DataFrame(search_progress['results'])
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reddit_Results')
    
    output.seek(0)
    filename = f"reddit_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/reset')
def reset():
    global search_progress
    search_progress = {
        'current': 0,
        'total': 0,
        'message': '',
        'is_running': False,
        'results': None,
        'error': None,
        'search_id': None
    }
    return redirect(url_for('index'))

if __name__ == '__main__':
    local_ip = get_local_ip()
    print(f"Local IP address detected: {local_ip}")
    print(f"Access the application at:")
    print(f"Local: http://localhost:5000")
    print(f"Network: http://{local_ip}:5000")
    
    app.run(host='0.0.0.0', port=5000, debug=True)