package user

import (
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type User struct {
	gorm.Model
	Email string `gorm:"uniqueIndex"`
}

type DTO struct {
	Email string
}

func Get(c *gin.Context)    {}
func Create(c *gin.Context) {}
