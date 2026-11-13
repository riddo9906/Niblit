#property copyright "Niblit chart intelligence â€” visualization only"
#property version "2.00"
#property indicator_chart_window
#property indicator_plots 0
#property indicator_buffers 0
input string SnapshotFile="";
input string StrategyFilter="all";
string prefix="NIBLIT.ANN.";
struct Drawing {string id,symbol,account,mode,kind,hex,label,explanation;int period;datetime t1,t2;double p1,p2;long expiry;};

string Hash(string value) {
 uchar data[],key[],result[];StringToCharArray(value,data,0,WHOLE_ARRAY,CP_UTF8);
 if(ArraySize(data)>0)ArrayResize(data,ArraySize(data)-1);
 if(CryptEncode(CRYPT_HASH_SHA256,data,key,result)<=0)return "";
 string text="";for(int i=0;i<ArraySize(result);i++)text+=StringFormat("%02x",result[i]);return text;
}
string AccountScope(){return "mt5-"+StringSubstr(Hash(AccountInfoString(ACCOUNT_SERVER)+":"+IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))),0,16);}
string SafeSymbol(){string name=_Symbol;StringReplace(name,"/","_");StringReplace(name,"\\","_");StringReplace(name,":","_");return name;}
void ClockReceipt(){
 FolderCreate("NiblitCharts",FILE_COMMON);
 int file=FileOpen("NiblitCharts\\clock_"+SafeSymbol()+"_"+AccountScope()+".tsv",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI|FILE_SHARE_READ,'\t',CP_UTF8);
 if(file==INVALID_HANDLE)return;
 FileWrite(file,"NIBLIT_CLOCK_V1",_Symbol,AccountScope(),(long)TimeTradeServer(),(long)TimeGMT(),(long)TimeCurrent());FileClose(file);
}
int Byte(string value,int at){string digits="0123456789abcdef";StringToLower(value);int a=StringFind(digits,StringSubstr(value,at,1)),b=StringFind(digits,StringSubstr(value,at+1,1));return MathMax(0,a)*16+MathMax(0,b);}
color Color(string value){return (color)(Byte(value,1)|(Byte(value,3)<<8)|(Byte(value,5)<<16));}
void ClearOwned(string keep=""){
 for(int i=ObjectsTotal(0,0,-1)-1;i>=0;i--){string name=ObjectName(0,i,0,-1);if(StringFind(name,prefix)==0 && (keep=="" || StringFind(keep,"|"+name+"|")<0))ObjectDelete(0,name);}
}
bool Draw(Drawing &d,string &name){
 name=prefix+d.id;
 ENUM_OBJECT kind=OBJ_TEXT;
 if(d.kind=="level"||d.kind=="entry"||d.kind=="stop"||d.kind=="target"||d.kind=="invalidation")kind=OBJ_HLINE;
 else if(d.kind=="zone")kind=OBJ_RECTANGLE;
 else if(d.kind=="trendline"||d.kind=="ray")kind=OBJ_TREND;
 if(ObjectFind(0,name)>=0 && (ENUM_OBJECT)ObjectGetInteger(0,name,OBJPROP_TYPE)!=kind)ObjectDelete(0,name);
 if(ObjectFind(0,name)<0 && !ObjectCreate(0,name,kind,0,d.t1,d.p1,d.t2,d.p2))return false;
 if(kind==OBJ_HLINE)ObjectSetDouble(0,name,OBJPROP_PRICE,0,d.p1);
 else {ObjectMove(0,name,0,d.t1,d.p1);if(kind==OBJ_RECTANGLE||kind==OBJ_TREND)ObjectMove(0,name,1,d.t2,d.p2);}
 ObjectSetInteger(0,name,OBJPROP_COLOR,Color(d.hex));ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
 ObjectSetInteger(0,name,OBJPROP_SELECTED,false);ObjectSetInteger(0,name,OBJPROP_HIDDEN,false);
 ObjectSetString(0,name,OBJPROP_TEXT,d.label);ObjectSetString(0,name,OBJPROP_TOOLTIP,d.explanation+"|EXP:"+IntegerToString(d.expiry));
 if(kind==OBJ_TEXT){ObjectSetInteger(0,name,OBJPROP_FONTSIZE,8);ObjectSetInteger(0,name,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);}
 if(kind==OBJ_TREND){ObjectSetInteger(0,name,OBJPROP_RAY_RIGHT,d.kind=="ray");ObjectSetInteger(0,name,OBJPROP_RAY_LEFT,false);}
 if(kind==OBJ_RECTANGLE){ObjectSetInteger(0,name,OBJPROP_FILL,false);ObjectSetInteger(0,name,OBJPROP_BACK,true);}
 // ObjectCreate queues work. Synchronous property readback verifies actual application.
 return ObjectFind(0,name)>=0 && MathAbs(ObjectGetDouble(0,name,OBJPROP_PRICE,0)-d.p1)<=MathMax(_Point*.51,MathAbs(d.p1)*1e-10);
}
void PruneExpired(){
 for(int i=ObjectsTotal(0,0,-1)-1;i>=0;i--){
  string name=ObjectName(0,i,0,-1);if(StringFind(name,prefix)!=0)continue;
  string info=ObjectGetString(0,name,OBJPROP_TOOLTIP);int at=StringFind(info,"|EXP:");
  if(at>=0 && StringToInteger(StringSubstr(info,at+5))<(long)TimeGMT())ObjectDelete(0,name);
 }
}
void OnTimer(){
 string current="NIBLIT.ANN."+StringSubstr(Hash(AccountScope()+":"+_Symbol+":"+IntegerToString((int)_Period)),0,12)+".";
 if(current!=prefix){ClearOwned();prefix=current;}PruneExpired();ClockReceipt();string snapshot=SnapshotFile==""?SafeSymbol()+"_"+AccountScope()+"_5m.tsv":SnapshotFile;
 if(StringFind(snapshot,"..")>=0||StringFind(snapshot,"\\")>=0||StringFind(snapshot,"/")>=0)return;
 int file=FileOpen("NiblitCharts\\"+snapshot,FILE_READ|FILE_CSV|FILE_COMMON|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE,'\t',CP_UTF8);
 if(file==INVALID_HANDLE)return;
 string schema=FileReadString(file),chartkey=FileReadString(file);int count=(int)StringToInteger(FileReadString(file));string revision=FileReadString(file);
 if(schema!="NIBLIT_CHART_V1"||count<0||count>80||StringLen(chartkey)!=64){FileClose(file);return;}
 Drawing rows[];ArrayResize(rows,count);bool valid=true;
 for(int i=0;i<count;i++){
  rows[i].id=FileReadString(file);rows[i].symbol=FileReadString(file);rows[i].period=(int)StringToInteger(FileReadString(file));rows[i].account=FileReadString(file);rows[i].mode=FileReadString(file);rows[i].kind=FileReadString(file);
  rows[i].t1=(datetime)StringToInteger(FileReadString(file));rows[i].p1=StringToDouble(FileReadString(file));rows[i].t2=(datetime)StringToInteger(FileReadString(file));rows[i].p2=StringToDouble(FileReadString(file));
  rows[i].hex=FileReadString(file);rows[i].label=FileReadString(file);rows[i].explanation=FileReadString(file);rows[i].expiry=StringToInteger(FileReadString(file));
  if(StringFind(rows[i].id,"ann_")!=0||StringLen(rows[i].id)!=28||!MathIsValidNumber(rows[i].p1)||!MathIsValidNumber(rows[i].p2)||rows[i].p1<=0||rows[i].p2<=0||rows[i].t1<=0||rows[i].t2<rows[i].t1)valid=false;
 }
 string footer=FileReadString(file);FileClose(file);if(!valid||footer!="END")return;
 string keep="";int accepted=0,failed=0;
 for(int i=0;i<count;i++){
  if(rows[i].symbol!=_Symbol||rows[i].period!=(int)_Period||rows[i].account!=AccountScope())continue;
  if(rows[i].mode!=(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO?"demo":"observe"))continue;
  if(rows[i].expiry<(long)TimeGMT())continue;
  if(StrategyFilter!="all" && StringFind(rows[i].label,StrategyFilter)<0)continue;
  string name;if(Draw(rows[i],name)){keep+="|"+name+"|";accepted++;}else failed++;
 }
 ClearOwned(keep);ChartRedraw(0);
 int ack=FileOpen("NiblitCharts\\"+snapshot+".ack",FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_ANSI|FILE_SHARE_READ,'\t',CP_UTF8);
 if(ack!=INVALID_HANDLE){
  FileWrite(ack,"NIBLIT_CHART_ACK_V1",chartkey,revision,_Symbol,(int)_Period,AccountScope(),accepted,failed,(long)TimeGMT());
  for(int i=0;i<count;i++){string name=prefix+rows[i].id;if(StringFind(keep,"|"+name+"|")>=0)FileWrite(ack,rows[i].id,name,(long)ObjectGetInteger(0,name,OBJPROP_TYPE),ObjectGetDouble(0,name,OBJPROP_PRICE,0),(long)ObjectGetInteger(0,name,OBJPROP_TIME,0));}
  FileClose(ack);
 }
}
int OnInit(){prefix="NIBLIT.ANN."+StringSubstr(Hash(AccountScope()+":"+_Symbol+":"+IntegerToString((int)_Period)),0,12)+".";ClearOwned();EventSetTimer(5);OnTimer();return INIT_SUCCEEDED;}
void OnDeinit(const int reason){EventKillTimer();ClearOwned();ChartRedraw(0);}
int OnCalculate(const int total,const int previous,const datetime &times[],const double &open[],const double &high[],const double &low[],const double &close[],const long &tickvolume[],const long &volume[],const int &spread[]){return total;}
