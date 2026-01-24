import pandas as pd
import json
import datetime

def test_serialization():
    # Simulate data from API (strings)
    data = [{"Tanggal": "2023-01-01", "Entitas": "A", "Judul": "B", "Isi": "C"}]
    df = pd.DataFrame(data)

    # Simulate Streamlit Data Editor conversion (if it happens)
    # Usually Streamlit keeps it as is unless typed, but let's assume it converts or user edits it as date
    df['Tanggal'] = pd.to_datetime(df['Tanggal'])

    print("DataFrame dtypes:")
    print(df.dtypes)

    row = df.iloc[0].to_dict()
    print(f"Row: {row}")

    try:
        json_str = json.dumps(row)
        print("Serialization Success!")
    except TypeError as e:
        print(f"Serialization Failed: {e}")

if __name__ == "__main__":
    test_serialization()
