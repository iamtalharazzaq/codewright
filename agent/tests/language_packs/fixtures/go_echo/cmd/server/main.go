package main

import (
	"github.com/labstack/echo/v4"

	"example.com/greet/internal/greeting"
)

func main() {
	e := echo.New()
	e.GET("/health", func(c echo.Context) error { return c.JSON(200, map[string]bool{"ok": true}) })
	api := e.Group("/api/v1")
	greetings := api.Group("/greetings")
	greetings.GET("/:id", greeting.Get)
	greetings.POST("", greeting.Create)
	e.Start(":9100")
}
