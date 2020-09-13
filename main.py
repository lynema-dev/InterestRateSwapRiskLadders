import matplotlib
import pandas as pd
import numpy as np
import math
import os
import copy
import matplotlib.pylab as plt
from pandas.plotting import register_matplotlib_converters

def priceInterestRateSwap (swap, valuationdate, dfCurves, dfFixings):

    #swap object
    if swap['direction'] == 'pay':
        fixedmultiplier = -1
    else:
        fixedmultiplier = 1

    swapid = swap['swapid']
    floatmultiplier = fixedmultiplier * -1
    effectivedate = pd.to_datetime(swap['effectivedate'])
    maturitydate = pd.to_datetime(swap['maturitydate'])
    forwardindex = swap['forwardindex']
    discountindex = swap['collateralindex']
    notional = swap['notional']
    fixedrate = swap['fixedrate']
    daycount = swap['daycount']
    valuationdate = pd.to_datetime(valuationdate)

    swapdetails = 'SwapID: ' + str(swapid) + ', ' + str(swap['direction']) + ' fixed @' \
        + str(fixedrate) + ', maturity: ' \
        + str(maturitydate.strftime('%d/%m/%Y')) + ', notional: ' + str(notional)

    #sub function to create roll schedule for each leg ([currentdate, forwardrate, discountrate,
    #nextrolldate] structure)
    def CreateRollSchedule(leg):
        leg = str(leg) + 'frequency'
        legschedule = []
        nextrolldate = effectivedate
        i = 0

        while nextrolldate < maturitydate:
            currentrolldate = effectivedate + pd.DateOffset(months = i * swap[leg])
            nextrolldate = effectivedate + pd.DateOffset(months = (i+1) * swap[leg])

            if leg == 'fixedfrequency':
                forwardrate = fixedrate
            else:
                #if currentrolldate is in the past, obtain a fixing instead of a forward rate
                if currentrolldate <= valuationdate:
                    forwardrate = dfFixings.loc[dfFixings['date'] 
                        == currentrolldate.strftime('%Y%m%d'), 'rate']
                    if forwardrate.empty:
                        print ('Missing Fixing Rate for ' + currentrolldate.strftime('%Y%m%d'))
                        exit()
                    else:
                        forwardrate = forwardrate.values[0]
                else:
                    forwardrate = ForwardRate(dfCurves, forwardindex, 
                        valuationdate, currentrolldate, 
                        swap[leg], daycount)

            paydatediscountrate = DiscountRate(dfCurves, discountindex, 
                valuationdate, nextrolldate, swap[leg], daycount)
            legscheduleelement = np.array([[currentrolldate, forwardrate, 
                paydatediscountrate, nextrolldate]])

            if i == 0:
                legschedule = legscheduleelement
            else:
                legschedule = np.vstack((legschedule, legscheduleelement))
            i = i + 1

        return legschedule

    #sub function to update a roll schedule discount and forward rates
    def UpdateRollSchedule(leg, legschedule, dfCurvesBumped):
        leg = str(leg) + 'frequency'

        for j in range(len(legschedule)):
            currentrolldate = legschedule[j,0]
            nextrolldate = legschedule[j,3]
            existingrate = legschedule[j,1]

            if leg == 'fixedfrequency' or (currentrolldate <= valuationdate):
                forwardrate = existingrate
            else:
                forwardrate = ForwardRate(dfCurvesBumped, forwardindex, valuationdate, 
                    currentrolldate, swap[leg], daycount)

            paydatediscountrate = DiscountRate(dfCurvesBumped, discountindex, 
                valuationdate, nextrolldate, swap[leg], daycount)    
            legschedule[j,1] = forwardrate
            legschedule[j,2] = paydatediscountrate

        return legschedule

    #sub function to calculate present value for each leg
    def LegPV(legschedule, notional, daycount):
        pv = 0
        for row in legschedule:
            pv = pv + notional * float(row[1]) * float(row[2]) \
                * (row[3]-row[0]).days / daycount    

        return pv
        

    floatlegschedule = CreateRollSchedule('float')
    if (swap['fixedfrequency'] == swap['floatfrequency']):
        fixedlegschedule = copy.copy(floatlegschedule)
        fixedlegschedule[:,1] = float(swap['fixedrate'])
    else:
        fixedlegschedule = CreateRollSchedule('fixed')

    presentvalue = LegPV(fixedlegschedule, notional * fixedmultiplier, daycount) \
        + LegPV(floatlegschedule, notional * -fixedmultiplier, daycount)
    
    #calculate the PV01 Risk Ladder by bumping each curve tenor point
    row = []
    columns = ['tenor', 'indexname', 'pv01']
    dfRiskLadder = pd.DataFrame(columns=columns)
    
    for index, row in dfCurves.iterrows():
        dfCurvesBumped = copy.copy(dfCurves)
        dfCurvesBumped.loc[index,'rate'] -= 0.0001 

        bumpedfixedlegschedule = UpdateRollSchedule('fixed', fixedlegschedule, dfCurvesBumped)
        bumpedfloatlegschedule = UpdateRollSchedule('float', floatlegschedule, dfCurvesBumped)
        
        pv01 = LegPV(bumpedfixedlegschedule, notional * fixedmultiplier, daycount) \
            + LegPV(bumpedfloatlegschedule, notional * -fixedmultiplier, daycount) - presentvalue
        
        row = [dfCurvesBumped.loc[index,'tenor'], dfCurvesBumped.loc[index,'indexname'], pv01]
        dfRiskLadder.loc[len(dfRiskLadder)] = row

    dfRiskLadderForward = dfRiskLadder[(dfRiskLadder['indexname'] == forwardindex)]
    pv01forward = round(dfRiskLadderForward['pv01'].sum(),1)
    dfRiskLadderCollateral = dfRiskLadder[(dfRiskLadder['indexname'] == discountindex)]
    pv01discount = round(dfRiskLadderCollateral['pv01'].sum(),1)

    #plot of results
    register_matplotlib_converters()
    fig = plt.figure(figsize=(8,8))
    fig.tight_layout(pad=3.0)
    title = swapdetails + '\n' + 'Present Value: ' + format(round(presentvalue,0),',.0f') \
        + ' ' + forwardindex + ' PV01: ' + format(round(pv01forward,0),',.0f') \
        + ', ' + discountindex + ' PV01: ' + format(round(pv01discount,0),',.0f')
    fig.suptitle(title, fontsize=10, fontweight='bold')

    plt.subplot(2,1,1)
    plt.bar(dfRiskLadderForward['tenor'],dfRiskLadderForward['pv01'], color = 'slategrey')
    plt.title(forwardindex + ' PV01 Risk Ladder', fontsize=9, fontweight='bold')
    plt.subplot(2,1,2)
    plt.bar(dfRiskLadderCollateral['tenor'],dfRiskLadderCollateral['pv01'], color = 'slategrey')
    plt.title(discountindex + ' PV01 Risk Ladder', fontsize=9, fontweight='bold')

    plt.show()


def curveSetUp(valuationdate, daycount):

    curdirectory = str(os.path.dirname(os.path.realpath(__file__))) + '\\Data Files\\'
    file = curdirectory + 'fixings.csv'
    dfFixings = pd.read_csv(file)
    file = curdirectory + 'curves.csv'
    dfCurves = pd.read_csv(file)
    valuationdate = pd.to_datetime(valuationdate)

    #add a tenor time field to the curve files to assist with interpolation 
    def tenor_to_time(x, valuationdate):
        tenortype = x[-1:]
        tenor = x[:-1]
        if tenortype == 'm':
            m = 1
        else:
            m = 12
        maturitydate = valuationdate + pd.DateOffset(months = m * int(tenor))
        return (maturitydate - valuationdate).days / daycount

    dfCurves['tenortime'] = [tenor_to_time(x, valuationdate) for x in dfCurves['tenor']]
    dfCurves.sort_values(['indexname','tenortime'], ascending=[False, True], inplace=True)

    dfFixings['date'] = pd.to_datetime(dfFixings['date']).dt.strftime('%Y%m%d')

    return (dfCurves, dfFixings)


def DiscountRate(dfCurves, indexname, valuationdate, dateval, frequency, daycount):

    df = dfCurves[dfCurves['indexname'] == indexname]

    tenor =  (dateval - valuationdate).days / daycount
    interpolatedrate = np.interp(tenor, df['tenortime'], df['rate'])
    frequency = 12 / frequency
    return 1 / ((1 + interpolatedrate / frequency) ** (frequency * tenor))

def ForwardRate(dfCurves, indexname, valuationdate, datefrom, frequency, daycount):

    df = dfCurves[dfCurves['indexname'] == indexname]

    tenorfrom =  (datefrom - valuationdate).days / daycount
    interpolatedratefrom = np.interp(tenorfrom, df['tenortime'], df['rate']) 

    dateto =  datefrom + pd.DateOffset(months = frequency)
    tenorto = (dateto - valuationdate).days / daycount
    tenordiff = tenorto - tenorfrom
    interpolatedrateto = np.interp(tenorto, df['tenortime'], df['rate'])
    frequency = 12 / frequency

    return ((((1 + interpolatedrateto / frequency) ** (tenorto * frequency)) 
    / ((1 + interpolatedratefrom / frequency) 
        ** (tenorfrom * frequency))) ** (1 / (tenordiff * frequency)) - 1) * frequency


def main():

    swap = {
        'swapid': 'x3453455',
        'direction': 'pay',
        'notional': 1000000,
        'fixedrate': 0.015,
        'effectivedate': '18/07/2020',
        'maturitydate': '18/07/2050',
        'floatfrequency': 6,
        'fixedfrequency':  6,
        'forwardindex': 'LIBOR',
        'collateralindex': 'SONIA',
        'daycount': 365.25
    }

    valuationdate = '18/07/2020'
    dfCurves, dfFixings = curveSetUp(valuationdate, swap['daycount'])
    pv = priceInterestRateSwap(swap, valuationdate, dfCurves, dfFixings)


if __name__ == '__main__':
    main()