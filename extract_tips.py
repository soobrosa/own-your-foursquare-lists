import csv
import json

def extract_tips():
    tips = []
    with open('input/tips.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip if this row looks like a header (contains column names)
            if row['id'] == 'id' and row['createdAt'] == 'createdAt':
                continue
            tips.append({
                'text': row['text'],
                'venue.id': row['venue.id']
            })
    return tips

if __name__ == '__main__':
    tips = extract_tips()
    print(f"Found {len(tips)} tips")
    
    # Save to JSON file
    with open('output/tips_extracted.json', 'w', encoding='utf-8') as f:
        json.dump(tips, f, ensure_ascii=False, indent=2)
    print("Saved to tips_extracted.json")
    # Print the first 5 tips that are actually the last 5 tips as example
    for tip in tips[:5]:
        print(f"\nVenue ID: {tip['venue.id']}")
        print(f"Text: {tip['text']}") 