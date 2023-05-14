from __future__ import annotations
from abc import ABC, abstractmethod
import pygsheets
import pandas as pd
import re
from typing import Tuple, List, Dict
from dateutil.relativedelta import relativedelta
from tabulate import tabulate

def CheckDateForm(Date:str):
    z = re.search('[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}$', Date)
    try:
        z.group()
    except:
        return False
    else:
        return True

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

    def __init__(self, Date:Tuple[str, str], Freq:str, 
                 Key:List[str], 
                 AccountSheet:pd.DataFrame) -> None:
        """

        Args:
            Date (Tuple[str, str]): (Start Date, End Date)
            Freq (str): 此帳目表的記帳頻率(ex: 表內每列代表"每月")。
            AccountSheet (pd.DataFrame): 帳目表。
            Key (List[str]): 索引用欄位名稱。
        """
        super().__init__()
        self._StartDate = Date[0]
        self._EndDate = Date[1]
        self._Date = Date
        self._Freq = Freq
        self._AccountSheet = AccountSheet
        self._Key = Key
    
    @property
    def Date(self):
        return self._Date
    
    @Date.setter
    def Date(self, value):
        self._Date = value
        self._StartDate = value[0]
        self._EndDate = value[1]
    
    @property
    def Freq(self):
        return self._Freq
    
    @property
    def StartDate(self):
        return self._StartDate
    
    @property
    def EndDate(self):
        return self._EndDate
    
    @property
    def AccountSheet(self):
        return self._AccountSheet
    
    @AccountSheet.setter
    def AccountSheet(self, Sheet):
        self._AccountSheet = Sheet
        # 使用Date而非_Date讓他自己填
        self.Date, self._Key = self.RetrieveAccountSheetFundamentalInfo(Sheet)
    
    @property
    def Key(self):
        return self._Key
    
    @staticmethod
    def RetrieveAccountSheetFundamentalInfo(AccountSheet):
        start_date = AccountSheet.Date.min()
        end_date = AccountSheet.Date.max()
        Date = (start_date, end_date)
        Key = AccountSheet.columns.to_list()
        Key.remove('Date')
        Key.remove('Cost/Income')
        return Date, Key
        
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
    
    def DataFrame2Account(self, DataFrame:pd.DataFrame, Freq:str='r', 
                          RearrangeSubset:List[str]=['Category'])->Account:
        AccountSheet = DataFrame.copy()

        # Datetime轉換
        AccountSheet = self.ReplaceColumnName(AccountSheet, 'Date', 
                                              ['Date', 'date', '日期'], 0)
        AccountSheet.Date = pd.to_datetime(AccountSheet.Date)
        AccountSheet.sort_values(by='Date',inplace=True)
        
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
        Date, Key = Account.RetrieveAccountSheetFundamentalInfo(AccountSheet)

        if Freq != 'r':
            assert Key == RearrangeSubset
            
        return Account(Date, Freq, Key, AccountSheet)
    
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
    
    
    def RearrangeAccountSheetByFreq(self, AccountSheet:pd.DataFrame, Freq:str='r', 
                                    subset:List[str]=['Category']):
        assert type(AccountSheet) == pd.DataFrame
        
        AccountSheet = AccountSheet.copy()
        if 'Label' in subset:
            temp = pd.DataFrame([], columns=AccountSheet.columns)
            for i in range(len(AccountSheet)):
                label = AccountSheet['Label'].iloc[i].split(',')
                Add = AccountSheet.iloc[i,:].copy()
                if len(label) > 1:
                    for l in label:
                        Add['Label'] = l
                        temp = temp.append(Add)                        
                else:
                    temp = temp.append(Add)
            AccountSheet = temp
        
        if Freq != 'r':     # Freq為row的話，不處理。
            AccountSheet.set_index('Date', inplace=True)
            AccountSheet = AccountSheet.groupby(by=subset).resample(Freq)['Cost/Income'].sum()
            AccountSheet = pd.DataFrame(AccountSheet).reset_index()
            temp_col = AccountSheet.pop('Date')
            AccountSheet.insert(0, 'Date', temp_col)        

        AccountSheet = AccountSheet.reset_index(drop=True)

        return AccountSheet
    
    def RearrangeAccountByFreq(self, account:Account, Freq:str, 
                               subset:List[str]=['Category']):

        assert isinstance(account, Account)
        
        # 建置Account
        AccountSheet = self.RearrangeAccountSheetByFreq(account.AccountSheet, 
                                                        Freq, subset)      

        Date, Key = Account.RetrieveAccountSheetFundamentalInfo(AccountSheet)
        
        if Freq != 'r':
            assert Key == subset
                
        return Account(Date, Freq, Key, AccountSheet)
    
    def Cut(self, account:Account, 
            start_date:str, end_date:str=None, inplace=False):
        
        if CheckDateForm(start_date) == False:
            print('Start date Form Error!!!')
            return 

        if end_date is not None:
            if CheckDateForm(end_date) == False:
                print('End date Form Error!!!')
                return 
            
        AccountSheet = account.AccountSheet

        AccountSheet = AccountSheet[start_date < AccountSheet.Date]
        if end_date is not None:
            AccountSheet = AccountSheet[AccountSheet.Date < end_date]

        if end_date is None:
            Date = (start_date, account.EndDate)
        else:
            Date = (start_date, end_date)

        if inplace == False:
            Freq = account.Freq
            Key = account.Key
            return Account(Date, Freq, Key, AccountSheet)
        else:
            # 自動更新除了Freq外的其他項(Date, Key)
            account.AccountSheet = AccountSheet

class StandardWebAccount():
    """_summary_
    由Google sheet開始的帳務物件，將會一次儲存"原始", "1d", "1m", "1y"的Acount
    供後續操作。
    """
    _TargetFreq = ['r', '1d', '1m', '1y']
    def __init__(self, sheet_url) -> None:
        self._sheet_url = sheet_url
        self._RawSheet = RetrieveWebSheet(sheet_url)
        self.Operator = AccountOperator()
        self.Reset()
    
    def Reset(self, subset:List[str]=['Category']):
        Accounts = {}
        if 'r' not in self._TargetFreq:
            self._TargetFreq.insert(0, 'r')
        for f in self._TargetFreq:
            if f == 'r':
                AccountRaw = self.Operator.DataFrame2Account(self._RawSheet, 'r')
                Accounts['r'] = AccountRaw
            else:
                Accounts[f] = self.Operator.RearrangeAccountByFreq(AccountRaw, 
                                                                   '1M', subset)
        self.Accounts = Accounts
    
    def Window(self, start_date:str, end_date:str=None):
        for f in self._TargetFreq:
            TargetAccount = self.Accounts[f]
            self.Accounts[f] = self.Operator.Cut(TargetAccount, start_date, end_date)

    def Show(self, target_f:str='r'):
        if target_f.lower() == 'all':
            for f in self._TargetFreq:
                sheet = self.Accounts[f].AccountSheet
                print(tabulate(sheet, headers='keys', tablefmt='pretty'))
        else:
            sheet = self.Accounts[target_f].AccountSheet
            print(tabulate(sheet, headers='keys', tablefmt='pretty'))

class GRule(ABC):
    def __init__(self, piece:Piece, event_time:int) -> None:
        super().__init__()
        self.start_date = None
        self.end_date = None
        self._unit = piece.to_list(remain_date = False)
        self.columns = piece.COLUMNS
        Index = self.columns.index('Date')
        self.non_date_columns = self.columns[:Index] + \
                                self.columns[Index+1:]
        self._event_time = event_time - 1

    def set_date(self, start_date:str, end_date:str):
        self.start_date = start_date
        self.end_date = end_date

    @abstractmethod
    def generate(self)->pd.DataFrame:
        if (self.start_date is None) or (self.end_date is None):
            raise ValueError('Please set start and end date first.')
        pass
    
    @property
    def unit(self):
        return self._unit

    @property
    def event_time(self):
        return self._event_time

class DaysGRule(GRule):

    def __init__(self, piece: Piece, event_time: int) -> None:
        super().__init__(piece, event_time)
    
    def generate(self) -> pd.DataFrame:
        super().generate()

        df = pd.DataFrame([], columns=self.columns)
        df.Date = [self.start_date, self.end_date]
        df.Date = pd.to_datetime(df.Date)
        df = df.set_index('Date')
        df = df.resample('1d').sum()
        df[self.non_date_columns] = self.unit
        df = df.reset_index()
        return df

class WeekGRule(GRule):

    def __init__(self, unit: Piece, event_time: int) -> None:
        super().__init__(unit, event_time)
    
    def generate(self) -> pd.DataFrame:
        super().generate()
        
        df = pd.DataFrame([], columns=self.columns)
        df.Date = [self.start_date, self.end_date]
        df.Date = pd.to_datetime(df.Date)
        df = df.set_index('Date')
        df = df.resample('1d').sum()
        df = df[df.index.dayofweek==self.event_time]
        df[self.non_date_columns] = self.unit
        df = df.reset_index()
        return df

class WeekDayGRule(GRule):
    
    def __init__(self, piece: Piece) -> None:
        super().__init__(piece, -1)
        Mon = WeekGRule(piece, 1)
        Tue = WeekGRule(piece, 2)
        Wed = WeekGRule(piece, 3)
        Thu = WeekGRule(piece, 4)
        Fri = WeekGRule(piece, 5)
        self.chain_of_rule = ChainOfGRule([Mon, Tue, Wed, Thu, Fri])
    
    def set_date(self, start_date: str, end_date: str):
        super().set_date(start_date, end_date)
        self.chain_of_rule.set_date(start_date, end_date)
    
    def generate(self) -> pd.DataFrame:
        super().generate()
        return self.chain_of_rule.generate()

class WeekendGRule(GRule):

    def __init__(self, piece: Piece, event_time: int) -> None:
        super().__init__(piece, event_time)
        Sat = WeekGRule(piece, 6)
        Sun = WeekGRule(piece, 7)
        self.chain_of_rule = ChainOfGRule([Sat, Sun])
    
    def set_date(self, start_date: str, end_date: str):
        super().set_date(start_date, end_date)
        self.chain_of_rule.set_date(start_date, end_date)
    
    def generate(self) -> pd.DataFrame:
        super().generate()
        return self.chain_of_rule.generate()

class ChainOfGRule():

    def __init__(self, GRuleList:List[GRule]) -> None:
        self.GRuleList = GRuleList
        self.start_date = None
        self.end_date = None
    
    def set_date(self, start_date:str, end_date:str):
        for rule in self.GRuleList:
            rule.set_date(start_date, end_date)
    
    def generate(self):
        DataFrameList = []
        for rule in self.GRuleList:
            DataFrameList.append(rule.generate())
        
        df = pd.concat(DataFrameList, axis=0)
        df = df.sort_values(by=['Date'])
        df = df.reset_index(drop=True)
        return df

# TODO: 還沒做檢查規則
class Piece(ABC):

    SETTING = ReadSetting()
    PAYMENT_TYPE = SETTING['PAYMENT_TYPE']
    PAYMENT_ADDORMINUS = SETTING['PAYMENT_ADDORMINUS']
    PAYMENT_SHORTCUT = SETTING['PAYMENT_SHORTCUT']
    COLUMNS = ['Date', 'Category', 'Name', 'Cost/Income', 'Label']

    def __init__(self, Date:str=None, Category:str=None, 
                 Name:str=None, Cost:int=None, Label:str=None):
        self._Date = pd.to_datetime(Date)
        self._Category = Category
        self._Name = Name
        self._Cost = Cost
        self._Label = Label
        self._Combine = [self._Date, self._Category, self._Name, 
                         self._Cost, self._Label]

    @property
    def Date(self):
        return self._Date
    
    @property
    def Category(self):
        return self._Category

    @property
    def Name(self):
        return self._Name

    @property
    def Cost(self):
        return self._Cost

    @property
    def Label(self):
        return self._Label

    def to_dataframe(self)->pd.DataFrame:
        df = pd.DataFrame(self._Combine).T
        df.columns = self.COLUMNS
        return df
    
    def to_list(self, remain_date=True)->list:
        if remain_date:
            return self._Combine
        else:
            Index = self.COLUMNS.index('Date')
            return self._Combine[:Index] + self._Combine[Index+1:]

if __name__ == '__main__':
    
    sheet_url = 'https://docs.google.com/spreadsheets/d/1Nz0rEL3-wik4jKjCBZzgb4fRzODqNZWCpg-GJ3Po5J8/edit#gid=0'
    print('Construct...')
    account = StandardWebAccount(sheet_url)
    account.Show()
    print('End')
    print('test week rule')
    p = Piece(Category='收入', Name='週薪', Cost=10000)
    rule = WeekGRule(p, 2)
    rule.set_date('2023-01-31', '2023-03-31')
    print(rule.generate())
    p2 = Piece(Category='食物', Name='早餐', Cost=45)
    rule2 = WeekDayGRule(p)
    rule2.set_date('2023-01-31', '2023-03-31')
    print(rule2.generate())
    print('End')

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