"""Write the complete agents.py file."""
content = open('agents_template.txt').read()

with open('app/agents.py', 'w') as f:
    f.write(content)

print("agents.py written successfully!")