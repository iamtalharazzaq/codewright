package greeting

import "github.com/labstack/echo/v4"

type Greeting struct {
	ID   uint
	Text string
}

func Get(c echo.Context) error    { return nil }
func Create(c echo.Context) error { return nil }
