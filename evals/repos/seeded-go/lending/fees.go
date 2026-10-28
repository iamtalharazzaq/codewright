package lending

import (
	"math"
	"time"
)

// DailyFeeCents is the late fee per day, in cents.
const DailyFeeCents = 25

// MaxFeeCents caps the late fee for one loan.
const MaxFeeCents = 1000

// LateFee is what a member owes for returning a loan at `returned`, in cents.
func LateFee(l Loan, returned time.Time) int {
	if !returned.After(l.Due) {
		return 0
	}
	days := int(math.Ceil(returned.Sub(l.Due).Hours() / 24)) // a started day counts as a day
	fee := days * DailyFeeCents
	if fee > MaxFeeCents {
		return MaxFeeCents
	}
	return fee
}

// TotalFees adds up the late fees of several loans returned at the same time.
func TotalFees(loans []Loan, returned time.Time) int {
	total := 0
	for _, l := range loans {
		total += LateFee(l, returned)
	}
	return total
}
