from pathlib import Path

path = Path(__file__).with_name('app.py')
text = path.read_text()
block = '''# -------------------------------
# Run App
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        create_default_users()
    app.run(debug=True)
'''
if text.count(block) > 1:
    text = text.replace(block, '', 1)
    path.write_text(text)
    print('Removed first duplicate run block')
else:
    print('No duplicate block found or only one block present')
