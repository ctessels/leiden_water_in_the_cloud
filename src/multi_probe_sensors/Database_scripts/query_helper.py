from prettytable import PrettyTable

def select(cursor, query):
    cursor.execute(query)
    rows = cursor.fetchall()
    column_names = [desc[0] for desc in cursor.description]
    table = PrettyTable()
    table.field_names = column_names

    for row in rows:
        table.add_row(row)

    print(table)