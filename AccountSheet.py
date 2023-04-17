from __future__ import annotations
from abc import ABC, abstractmethod
import pygsheets
import pandas as pd
from typing import Tuple, List, Dict
from dateutil.relativedelta import relativedelta

def TextGetNotationPairPos(text:str, notation:str, 
                           Msg:bool=True)->List(Tuple(int, int)):
    """
    在text中搜尋notation，兩兩一組，依序紀錄成Tuple、存於List中，並回傳。
    主要用於尋找文件中表示string(由兩個"或兩個'包夾)之位置，也可用於抓取註解位置
    (Ex:由兩個%%%包夾)。
    """
    l = len(notation) - 1
    PairPos = []
    count = 0
    for i in range(len(text)-l):
        t = text[i:(i+l+1)]
        if t == notation:
            count += 1
            if count % 2 == 0:
                pos = (pos, i+l)
                PairPos.append(pos)
            else:
                pos = i
    
    if count % 2 != 0 and Msg:
        print(f'於第{pos}個字下有單獨一組對應的notation。')
    
    return PairPos

def TextValueTransform(Value:str)->float:
    """
    在文字檔以"或'作為string型態的表示法下，將文字的Value轉換為合適的型態。
    Ex: float, 依"或'之包夾處轉為string。
    """
    DoubleQuotePos = TextGetNotationPairPos(Value, '"', False)
    SingleQuotePos = TextGetNotationPairPos(Value, "'", False)
    # 為數字
    if len(DoubleQuotePos) == 0 and len(SingleQuotePos) == 0:
        try:
            number = float(Value)
        except ValueError:
            raise ValueError("""若Value非數字而為文字，須以'或"包夾住。""")
        else:
            return float(Value)
    # 有"或'，應為String
    PairPos = sorted(DoubleQuotePos+SingleQuotePos)[0]
    
    if len(DoubleQuotePos) > 1 and PairPos in DoubleQuotePos:
        raise ValueError("""Value以"對應，但超過一組"。""")
    if len(SingleQuotePos) > 1 and PairPos in SingleQuotePos:
        raise ValueError("""Value以'對應，但超過一組'。""")
    
    ## 確認Pos為最外層
    if PairPos[0] != 0 or PairPos[1] != len(Value)-1:
        raise ValueError("""Value最近的兩個「"」或「'」不在頭尾。""")
    else:
        return Value[1:-1]

def TextRemoveByPairPos(text:str, PairPos:List[Tuple(int, int)])->str:
    new_text = ''
    head = 0
    for pos in PairPos:
        new_text += text[head:pos[0]]
        head = pos[1]+1
    new_text += text[head:]
    return new_text

def TextRemoveAnnotation(text:str, notation:str=r'%%%')->str:
    PairPos = TextGetNotationPairPos(text, notation)
    new_text = TextRemoveByPairPos(text, PairPos)
    return new_text

def TextListTransform(text):
    TransList = []
    values = text[1:-1].split(',')
    for v in values:
        TransList.append(TextValueTransform(v))
    return TransList

def TextDictTransform(text):
    TransDict = {}
    KVPairs = text[1:-1].split(',')
    for KV in KVPairs:
        key, value = KV.split(':')
        key = TextValueTransform(key)
        value = TextValueTransform(value)
        TransDict[key] = value
    return TransDict

def ReadSetting(file:str=r'.\Setting.txt'):
    f = open(file, 'r', encoding='utf-8')
    
    # concat
    words = ''
    for l in f.readlines():
        words += l
    
    # preprocess
    words = TextRemoveAnnotation(words)
    words = words.replace('\t', '')
    words = words.replace('\n', '')
    words = words.replace(' ','')
    words = words.split(';')
    while '' in words:
        words.remove('')
    
    Setting = {}
    for w in words:
        key, value = w.split('=')
        if value[0] == '[' and value[-1] == ']':
            value = TextListTransform(value)
        elif value[0] == '{' and value[-1] == '}':
            value = TextDictTransform(value)
        else:
            value = TextValueTransform(value)
        Setting[key] = value
    
    f.close()
    return Setting

class Account(ABC):
    SETTING = ReadSetting()
    PAYMENT_TYPE = SETTING['PAYMENT_TYPE']
    PAYMENT_ADDORMINUS = SETTING['PAYMENT_ADDORMINUS']
    PAYMENT_SHORTCUT = SETTING['PAYMENT_SHORTCUT']

    def __init__(self, Date:Tuple[str, str], Freq:str, 
                 AccountSheet:Dict[str, pd.DataFrame]) -> None:
        """

        Args:
            Date (Tuple[str, str]): (Start Date, End Date)
            Freq (str): 此帳目表的記帳頻率(ex: 表內每列代表"每月")。
            AccountSheet (Dict[str, pd.DataFrame]): 
                帳目表，key值為類別，value為該類別下帳目表。
        """
        super().__init__()
        self.StartDate = Date[0]
        self.EndDate = Date[1]
        self.Date = Date
        self.Freq = Freq
        self.AccountSheet = AccountSheet
    
    def GetStartDate(self):
        return self.StartDate
    
    def GetEndDate(self):
        return self.EndDate

    def GetDate(self):
        return self.Date

def RetrieveWebSheet(url, sheet_title='工作表1', key_file_path=r'./key.json'):
    gc = pygsheets.authorize(service_account_file=key_file_path)
    sh = gc.open_by_url(url)
    
    sheets_names = [ws.title for ws in sh.worksheets()]
    if sheet_title in sheets_names:
        ws = sh.worksheet_by_title(sheet_title)
        return ws.get_as_df()
    else:
        return "錯誤的sheet_title。"

class AccountOperator(ABC):
    def __init__(self) -> None:
        super().__init__()
    
    def DataFrame2Account(self, DataFrame:pd.DataFrame, Freq:str='Auto', 
                          RearrangeSubset:List[str]=['Category'])->Account:
        AccountSheet = DataFrame.copy()

        # Datetime轉換
        AccountSheet = self.ReplaceColumnName(AccountSheet, 'Date', 
                                              ['Date', 'date', '日期'], 0)
        AccountSheet.Date = pd.to_datetime(AccountSheet.Date)
        AccountSheet = AccountSheet.set_index('Date')
        AccountSheet.sort_index(inplace=True)
        # 其餘欄位(類別、項目名稱、支出/收入、標籤)
        AccountSheet = self.ReplaceColumnName(AccountSheet, 'Category', 
                                              ['類別', 'Category', 'category'], 1)
        AccountSheet = self.ReplaceColumnName(AccountSheet, 'Name', 
                                              ['項目名稱', '項目', '名稱', 
                                               'Name', 'name'], 1)
        AccountSheet = self.ReplaceColumnName(AccountSheet, 'Cost/Income', 
                                              ['支出/收入', '支出', 'Cost', 'cost', 
                                               'Cost/Income', 'cost/income'], 2)
        AccountSheet = self.ReplaceColumnName(AccountSheet, 'Label', 
                                              ['標籤', 'Label', 'label'], 3)
            
        # 分析頻率，並調整日期
        if Freq == 'Auto':
            Freq = self.AnalysisAcountFreq(AccountSheet)
        
        AccountSheet = self.RearrangeAccountSheetByFreq(AccountSheet, Freq, RearrangeSubset)
        
        # 建置Account
        Account()
    
    def ReplaceColumnName(self, DataFrame:pd.DataFrame, 
                          replace:str, 
                          valid_name_list:List[str], 
                          default_index:int)->pd.DataFrame:
        columns = DataFrame.columns.to_list()
        for v in valid_name_list:
            if v in columns:
                break
            else:
                v = columns[default_index]
        temp_col = DataFrame.pop(v)
        DataFrame.insert(default_index, replace, temp_col)
        return DataFrame
    
    def AnalysisAcountFreq(self, AccountSheet:pd.DataFrame):
        if isinstance(AccountSheet, Account):
            print("請輸入AccountSheet，而非Account。")
            AccountSheet = AccountSheet.AccountSheet
            
        date_count = AccountSheet.Date.diff(1).min().days
        
        if date_count == 0:
            return 'r'  # by Row
        elif date_count > 0 and date_count < 28:
            return '1d'  # Daily
        elif date_count >= 28 and date_count < 365:
            return '1m'  # monthly
        elif date_count >= 365:
            return '1y'  # yearly
        else:
            raise ValueError("date_count < 0.")
    
    
    def RearrangeAccountSheetByFreq(self, AccountSheet:pd.DataFrame, Freq:str, 
                                    subset:List[str]=['Category']):
        if isinstance(AccountSheet, Account):
            print("請輸入AccountSheet，而非Account。")
            Account = AccountSheet
            AccountSheet = AccountSheet.AccountSheet
        
        if Freq != 'r':     # Freq為row的話，不處理。
            AccountSheet = AccountSheet.groupby(by=subset).resample(Freq).sum()
            AccountSheet.set_index('Date', inplace=True)
        
        if isinstance(AccountSheet, Account):
            Account.AccountSheet = AccountSheet
            return Account
        else:
            return AccountSheet
    
if __name__ == '__main__':
    
    sheet_url = 'https://docs.google.com/spreadsheets/d/1Nz0rEL3-wik4jKjCBZzgb4fRzODqNZWCpg-GJ3Po5J8/edit#gid=0'
    

# gc = pygsheets.authorize(service_account_file=r'./key.json')

# survey_url = 'https://docs.google.com/spreadsheets/d/1Nz0rEL3-wik4jKjCBZzgb4fRzODqNZWCpg-GJ3Po5J8/edit#gid=0'
# sh = gc.open_by_url(survey_url)

# ws = sh.worksheet_by_title('工作表1')
# ws.update_value('A2', 'test')

# df1 = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
# ws.set_dataframe(df1, 'A2', copy_index=False, nan='')

# val = ws.get_value('A1')
# print(val)
# df2 = ws.get_as_df(start='A2', 
#                    empty_value='', include_tailing_empty=False, 
#                    numerize=False) # index 從 1 開始算
# print(df2)