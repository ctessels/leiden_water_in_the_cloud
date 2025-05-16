import pandas as pd
import numpy as np


def add_6H_timebox(df):
    
    # Define the conditions and corresponding values
    conditions = [
        (df['datum_tijd'].dt.time >= pd.to_datetime('00:00:00').time()) & (df['datum_tijd'].dt.time < pd.to_datetime('06:00:00').time()),
        (df['datum_tijd'].dt.time >= pd.to_datetime('06:00:00').time()) & (df['datum_tijd'].dt.time < pd.to_datetime('12:00:00').time()),
        (df['datum_tijd'].dt.time >= pd.to_datetime('12:00:00').time()) & (df['datum_tijd'].dt.time < pd.to_datetime('18:00:00').time()),
        (df['datum_tijd'].dt.time >= pd.to_datetime('18:00:00').time()) | (df['datum_tijd'].dt.time < pd.to_datetime('00:00:00').time())
    ]
    values = ['00:00:00', '06:00:00', '12:00:00', '18:00:00']

    # Apply the conditions and assign values to the 'adjusted_datetime' column
    df['datum_tijdbox'] = np.where(conditions[0], df['datum_tijd'].dt.strftime('%Y-%m-%d') + ' ' + values[0],
                                    np.where(conditions[1], df['datum_tijd'].dt.strftime('%Y-%m-%d') + ' ' + values[1],
                                                np.where(conditions[2], df['datum_tijd'].dt.strftime('%Y-%m-%d') + ' ' + values[2], 
                                                        df['datum_tijd'].dt.strftime('%Y-%m-%d') + ' ' + values[3])))
    df['datum_tijdbox'] = pd.to_datetime(df['datum_tijdbox'])

    return df


def resample(df, resample_freq):
    df_resample = []
    # Iterate over each 'locatie' group
    for group_name, group_df in df.groupby('locatie'):

        # Resample the DataFrame within each group over the index level 'datum_tijd' with a frequency of 6 hours
        resampled_group_df = group_df['meetwaarde'].resample(resample_freq, level='datum_tijd').agg(['min', 'max', 'mean']).reset_index()

        # Fill missing intervals with NaT
        resampled_group_df['datum_tijd'] = resampled_group_df['datum_tijd'].fillna(pd.NaT)
        resampled_group_df['locatie'] = group_name

        # Add the resampled DataFrame to the list
        df_resample.append(resampled_group_df)

    # Concatenate the resampled DataFrames
    df = pd.concat(df_resample)
    df = df[['locatie','datum_tijd','min','max','mean']]
    df[['min', 'max', 'mean']] = df[['min', 'max', 'mean']].fillna(method='ffill')

    return df


def anonymize_location(df):

    mapping = {loc: id for id, loc in enumerate(df['locatie'].unique())}
    df['locatie'] = df['locatie'].map(mapping)
    df.drop(columns=['min_meetwaarde', 'max_meetwaarde'], inplace=True)

    df.to_excel('./data/dataframe.xlsx')

    inverse_mapping = {id: loc for loc, id in mapping.items()}
    df['locatie'] = df['locatie'].map(inverse_mapping)
