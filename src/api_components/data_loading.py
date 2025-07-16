import pandas as pd


def get_all_data():

    # Laad dim_sensor
    df_dim_sensor = pd.read_excel(
        './data/dim_sensor_documentation.xlsx', sheet_name='dim_sensor_fase_1')

    # Laad fact_sensor
    columns_to_load = ['gateway_receive_time', 'device', 'value']
    df_fact_sensor = pd.read_excel(
        './data/Permittivity_updated.xlsx', usecols=columns_to_load)
    df_fact_sensor.drop_duplicates(inplace=True)

    # Laad KNMI data
    file_name = "etmgeg_240.txt"
    df_KNMI = pd.read_csv(f'./data/{file_name}',
                          skiprows=51, sep=',', low_memory=False)

    df_KNMI.columns = [x.strip() for x in df_KNMI.columns]
    df_KNMI = df_KNMI[['# STN', 'YYYYMMDD', 'FG', 'TG',
                       'SQ', 'DR', 'RH', 'PG', 'NG', 'UG', 'EV24']]
    df_KNMI.columns = ['weerstation', 'datum', 'windsnelheid', 'temperatuur', 'zonneschijn_duur',
                       'neerslag_duur', 'neerslag', 'luchtdruk', 'bewolking', 'vochtigheid', 'verdamping']

    # filter op weerstation schiphol = 240, deze ligt het dichts bij Leiden
    df_KNMI = df_KNMI[df_KNMI['weerstation']
                      == 240].drop(columns=['weerstation'])

    # Zet de datatypes goed
    df_KNMI['datum'] = pd.to_datetime(df_KNMI['datum'], format='%Y%m%d')

    for col in df_KNMI.columns:
        if col not in ['datum', 'weerstation']:
            df_KNMI[col] = pd.to_numeric(df_KNMI[col], errors='coerce')

    # Laad weersdata Leiden (weerstation Zusterhof)
    file_name = "weerdata_leiden.xlsx"
    columns_to_load = ['date', 'avg temp (c)', 'rainfall (mm)']
    df_weerstation_Leiden = pd.read_excel(
        f'./data/{file_name}', usecols=columns_to_load)
    df_weerstation_Leiden.columns = ['datum', 'temperatuur', 'neerslag']

    return df_dim_sensor, df_fact_sensor, df_KNMI, df_weerstation_Leiden


if __name__ == "__main__":
    get_all_data()
