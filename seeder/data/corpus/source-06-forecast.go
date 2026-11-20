// Cash forecast for project Kyma (PRJ-KYM-8255).
//
// Proprietary and confidential. Property of Aspida Demo Consulting. Do not distribute.
// Projects the firm's cash position week by week from open invoices, signed orders and
// fixed costs, using each client's own payment history.
package forecast

import (
	"errors"
	"math"
	"sort"
	"time"
)

// Receivable is an invoice that has been issued and not yet paid.
type Receivable struct {
	ClientID string
	Amount   float64
	DueOn    time.Time
}

// Order is signed work that will be invoiced at the end of each month it runs.
type Order struct {
	ClientID     string
	MonthlyValue float64
	Start        time.Time
	Months       int
}

// PaymentHabit says how late a client usually pays, in days after the due date.
type PaymentHabit struct {
	ClientID    string
	AverageLate float64
	Samples     int
}

// Week is one row of the forecast.
type Week struct {
	Starting time.Time
	Inflow   float64
	Outflow  float64
	Closing  float64
}

var errNoWeeks = errors.New("forecast: at least one week is required")

const defaultLateDays = 12.0

// expectedLate falls back to the firm-wide average until a client has five paid invoices.
func expectedLate(clientID string, habits []PaymentHabit) float64 {
	for _, habit := range habits {
		if habit.ClientID == clientID && habit.Samples >= 5 {
			return habit.AverageLate
		}
	}
	return defaultLateDays
}

func weekIndex(start, day time.Time) int {
	return int(math.Floor(day.Sub(start).Hours() / (24 * 7)))
}

// Build returns the forecast for the given number of weeks from start.
func Build(start time.Time, weeks int, opening float64, receivables []Receivable,
	orders []Order, habits []PaymentHabit, weeklyFixedCost float64) ([]Week, error) {
	if weeks < 1 {
		return nil, errNoWeeks
	}
	inflow := make([]float64, weeks)
	for _, receivable := range receivables {
		late := time.Duration(expectedLate(receivable.ClientID, habits)*24) * time.Hour
		index := weekIndex(start, receivable.DueOn.Add(late))
		if index < 0 {
			index = 0
		}
		if index < weeks {
			inflow[index] += receivable.Amount
		}
	}
	for _, order := range orders {
		for month := 0; month < order.Months; month++ {
			invoiced := order.Start.AddDate(0, month+1, 0)
			late := time.Duration((30+expectedLate(order.ClientID, habits))*24) * time.Hour
			index := weekIndex(start, invoiced.Add(late))
			if index >= 0 && index < weeks {
				inflow[index] += order.MonthlyValue
			}
		}
	}
	rows := make([]Week, weeks)
	balance := opening
	for index := range rows {
		balance += inflow[index] - weeklyFixedCost
		rows[index] = Week{
			Starting: start.AddDate(0, 0, 7*index),
			Inflow:   inflow[index],
			Outflow:  weeklyFixedCost,
			Closing:  balance,
		}
	}
	return rows, nil
}

// LowestPoint is the week in which the closing balance is smallest.
func LowestPoint(rows []Week) Week {
	sorted := append([]Week(nil), rows...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Closing < sorted[j].Closing })
	return sorted[0]
}

// Concentration is the share of expected inflow that comes from the largest client.
func Concentration(receivables []Receivable) float64 {
	totals := map[string]float64{}
	sum, largest := 0.0, 0.0
	for _, receivable := range receivables {
		totals[receivable.ClientID] += receivable.Amount
		sum += receivable.Amount
	}
	for _, total := range totals {
		largest = math.Max(largest, total)
	}
	if sum == 0 {
		return 0
	}
	return largest / sum
}
