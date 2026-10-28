package main

import (
	"github.com/gin-gonic/gin"

	"example.com/shop/internal/user"
)

func main() {
	r := gin.Default()
	r.GET("/health", func(c *gin.Context) { c.JSON(200, gin.H{"ok": true}) })
	api := r.Group("/api/v1")
	users := api.Group("/users")
	users.GET("/:id", user.Get)
	users.POST("", user.Create)
	r.Run(":9000")
}
